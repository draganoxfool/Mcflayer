from __future__ import annotations

import asyncio
import uuid

import numpy as np

from pyflayer.bot import Bot
from pyflayer.events import (
    BlockUpdateEvent,
    ChunkLoadEvent,
    EntitySpawnEvent,
    InventoryChangedEvent,
)
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.testing import FakeServer

STONE = 16
DIRT = 48


def chunk_payload() -> bytes:
    states = np.zeros(4096, dtype=np.uint16)
    states[:256] = STONE  # y=64 layer of section 4
    return states.astype("<u2").tobytes() + bytes(2048) + bytes(2048) + bytes([1]) * 256


def partial_chunk_payload() -> bytes:
    states = np.zeros(4096, dtype=np.uint16)
    states[:256] = DIRT  # y=80 layer of section 5; no biomes on a partial update
    return states.astype("<u2").tobytes() + bytes(2048) + bytes(2048)


async def _run(bot: Bot) -> asyncio.Task[None]:
    task = asyncio.create_task(bot.run())
    await asyncio.sleep(0)
    return task


async def _wait(predicate: object, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():  # type: ignore[operator]
            await asyncio.sleep(0.01)


async def test_bot_applies_chunks_blocks_entities_and_inventory() -> None:
    async with FakeServer() as server:
        bot = Bot("Steve", host="127.0.0.1", port=server.port, use_srv=False)
        await bot.connect()
        task = await _run(bot)

        chunks: list[ChunkLoadEvent] = []
        blocks: list[BlockUpdateEvent] = []
        entities: list[EntitySpawnEvent] = []
        inventory: list[InventoryChangedEvent] = []
        bot.events.subscribe(ChunkLoadEvent, chunks.append)
        bot.events.subscribe(BlockUpdateEvent, blocks.append)
        bot.events.subscribe(EntitySpawnEvent, entities.append)
        bot.events.subscribe(InventoryChangedEvent, inventory.append)

        server.send_play(
            "map_chunk",
            {"x": 0, "z": 0, "groundUp": True, "bitMap": 1 << 4, "chunkData": chunk_payload()},
        )
        await _wait(lambda: bool(chunks))
        assert bot.world.is_loaded(chunks[0].pos)
        assert bot.world.block_at(BlockPos(0, 64, 0)).name == "stone"
        assert chunks[0].non_air == 256

        server.send_play(
            "map_chunk",
            {"x": 0, "z": 0, "groundUp": False, "bitMap": 1 << 5, "chunkData": partial_chunk_payload()},
        )
        await _wait(lambda: len(chunks) == 2)
        assert bot.world.block_state_id(BlockPos(0, 64, 0)) == STONE
        assert bot.world.block_state_id(BlockPos(0, 80, 0)) == DIRT

        server.send_play(
            "block_change",
            {"location": {"x": 3, "y": 64, "z": 4}, "type": DIRT},
        )
        await _wait(lambda: bool(blocks))
        assert bot.world.block_state_id(BlockPos(3, 64, 4)) == DIRT
        assert blocks[0].old_state_id == STONE

        player_uuid = uuid.uuid4()
        server.send_play(
            "named_entity_spawn",
            {
                "entityId": 12,
                "playerUUID": player_uuid,
                "x": 32,
                "y": 2080,
                "z": 32,
                "yaw": 0,
                "pitch": 0,
                "currentItem": 0,
                "metadata": {2: "Steve"},
            },
        )
        await _wait(lambda: bool(entities))
        entity = bot.entities.get(12)
        assert entity is not None
        assert entity.uuid == str(player_uuid)
        assert entity.position == Vec3(1.0, 65.0, 1.0)

        server.send_play(
            "set_slot",
            {"windowId": 0, "slot": 36, "item": ItemStack(item_id=1, count=1)},
        )
        await _wait(lambda: bool(inventory))
        assert bot.inventory.held_item is not None
        assert bot.inventory.held_item.item_id == 1

        await bot.close()
        await asyncio.gather(task, return_exceptions=True)
