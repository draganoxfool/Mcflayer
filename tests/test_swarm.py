from __future__ import annotations

import asyncio
import random

import numpy as np
import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.data.loader import McData
from pyflayer.errors import ChunkNotLoaded
from pyflayer.events import BlockUpdateEvent, ChunkLoadEvent, PhysicsTickEvent
from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.swarm import (
    Blackboard,
    BlackboardChangedEvent,
    BotCluster,
    BotKickedEvent,
    ClaimRegistry,
    LoginStaggerPolicy,
    PathCache,
    SharedWorldRegistry,
)
from pyflayer.swarm.cluster import BotSpawnEvent
from pyflayer.testing import FakeServer
from pyflayer.world import ChunkColumn, WorldKey

STONE = 16
DIRT = 48


def _column(pos: ChunkPos | None = None, state: int = STONE) -> ChunkColumn:
    return ChunkColumn(pos or ChunkPos(0, 0)).with_block(0, 64, 0, state)


def _registry() -> SharedWorldRegistry:
    return SharedWorldRegistry(McData.load("1.8.9"), server="test:25565")


def _chunk_payload() -> bytes:
    states = np.zeros(4096, dtype=np.uint16)
    states[:256] = STONE  # y=64 layer of section 4
    return states.astype("<u2").tobytes() + bytes(2048) + bytes(2048) + bytes([1]) * 256


# ---------------------------------------------------------------------------- shared world


def test_shared_world_decodes_once_and_tracks_refs() -> None:
    registry = _registry()
    first = registry.view(bot_id=1)
    second = registry.view(bot_id=2)
    column = _column()

    first.apply_chunk(column)
    assert first.is_loaded(ChunkPos(0, 0))
    assert first.block_at(BlockPos(0, 64, 0)).name == "stone"
    assert not second.is_loaded(ChunkPos(0, 0))
    with pytest.raises(ChunkNotLoaded):
        second.block_state_id(BlockPos(0, 64, 0))

    # The second bot receives its own copy from its own connection; the store keeps the first.
    second.apply_chunk(_column())
    assert second.is_loaded(ChunkPos(0, 0))
    stats = registry.stats()
    assert stats["chunks"] == 1
    assert stats["refs"] == 2
    assert stats["sections"] == 1
    assert stats["bytes"] > 0

    first.clear()
    assert not first.is_loaded(ChunkPos(0, 0))
    assert len(registry) == 1
    second.clear()
    assert len(registry) == 0


def test_shared_world_replaces_without_extra_ref_and_applies_updates_once() -> None:
    registry = _registry()
    first = registry.view(bot_id=1)
    second = registry.view(bot_id=2)
    first.apply_chunk(_column())
    second.apply_chunk(_column())
    assert registry.store(0).stats()["refs"] == 2

    first.apply_chunk(_column(state=DIRT))
    assert registry.store(0).stats()["refs"] == 2
    assert second.block_state_id(BlockPos(0, 64, 0)) == DIRT

    assert first.store.apply_block(BlockPos(0, 64, 0), STONE)
    assert not first.store.apply_block(BlockPos(0, 64, 0), STONE)


def test_shared_world_dimension_switch_rebinds_store() -> None:
    registry = _registry()
    view = registry.view(bot_id=7)
    view.apply_chunk(_column())
    assert len(registry.store(0)) == 1

    view.set_dimension(-1)
    assert view.dimension == -1
    assert len(registry.store(0)) == 0
    assert view.is_loaded(ChunkPos(0, 0)) is False

    view.apply_chunk(_column(ChunkPos(0, 0), DIRT))
    assert len(registry.store(-1)) == 1
    assert view.block_state_id(BlockPos(0, 64, 0)) == DIRT
    view.detach()
    assert len(registry.store(-1)) == 0


def test_shared_world_find_blocks_only_sees_held_chunks() -> None:
    registry = _registry()
    first = registry.view(bot_id=1)
    second = registry.view(bot_id=2)
    first.apply_chunk(_column(ChunkPos(0, 0)))
    second.apply_chunk(_column(ChunkPos(5, 5)))
    assert first.find_blocks("stone", within=100) == [BlockPos(0, 64, 0)]
    assert second.find_blocks("stone", within=200) == [BlockPos(80, 64, 80)]


# ---------------------------------------------------------------------------- stagger


async def test_login_stagger_spaces_logins_and_backs_off() -> None:
    clock = FakeClock()
    policy = LoginStaggerPolicy(5.0, jitter=0.0, clock=clock, rng=random.Random(0))

    async def login() -> float:
        async with policy.slot():
            return clock.monotonic()

    first = asyncio.create_task(login())
    await asyncio.sleep(0)
    assert await first == 0.0

    second = asyncio.create_task(login())
    await asyncio.sleep(0)
    assert not second.done()
    await clock.advance_async(5.0)
    assert await second == 5.0

    assert policy.is_throttle_reason("Connection throttled! Please wait")
    assert policy.record_throttle("Connection throttled! Please wait") == 10.0
    assert policy.interval == 10.0
    assert policy.record_throttle("You are banned") == 10.0
    policy.record_success()
    assert policy.interval == 5.0


# ---------------------------------------------------------------------------- coordination


def test_claim_registry_ttl_regions_and_release() -> None:
    clock = FakeClock()
    claims = ClaimRegistry(clock=clock)
    pos = BlockPos(1, 64, 1)

    assert claims.claim("Miner1", pos, ttl=10)
    assert not claims.claim("Miner2", pos)
    assert claims.owner_of(pos) == "Miner1"
    assert claims.is_claimed(pos, by="Miner1")
    assert not claims.is_claimed(pos, by="Miner2")

    clock.advance(10.0)
    assert claims.owner_of(pos) is None

    assert claims.claim_region("Miner1", BlockPos(0, 0, 0), BlockPos(4, 4, 4))
    assert not claims.claim_region("Miner2", BlockPos(3, 3, 3), BlockPos(6, 6, 6))
    assert claims.claim_region("Miner2", BlockPos(10, 0, 10), BlockPos(12, 4, 12))
    assert claims.owner_of(BlockPos(2, 2, 2)) == "Miner1"
    assert claims.owner_of(BlockPos(11, 1, 11)) == "Miner2"

    assert claims.claim("Miner1", BlockPos(20, 64, 20))
    assert claims.release_owner("Miner1") == 2
    assert claims.owner_of(BlockPos(2, 2, 2)) is None
    assert claims.owner_of(BlockPos(20, 64, 20)) is None
    assert claims.release("Miner1", BlockPos(20, 64, 20)) is False

    assert claims.release_region("Miner2", BlockPos(11, 1, 11))
    assert claims.owner_of(BlockPos(11, 1, 11)) is None


async def test_blackboard_change_events_waiter_and_ttl() -> None:
    clock = FakeClock()
    board = Blackboard(clock=clock)
    changes: list[BlackboardChangedEvent] = []
    board.events.subscribe(BlackboardChangedEvent, changes.append)

    assert board.set("diamonds", BlockPos(3, 12, 4), owner="Miner1") == 1
    assert board.get("diamonds") == BlockPos(3, 12, 4)
    assert board.get("missing", 0) == 0

    waiter = asyncio.create_task(board.wait_for("diamonds"))
    await asyncio.sleep(0)
    board.set("diamonds", BlockPos(5, 12, 6), owner="Miner2")
    assert await waiter == BlockPos(5, 12, 6)
    await asyncio.sleep(0.01)
    assert len(changes) == 2

    board.set("temporary", 1, ttl=2.0)
    assert "temporary" in board
    clock.advance(2.0)
    assert "temporary" not in board
    assert board.delete("diamonds")
    assert not board.delete("diamonds")


def test_path_cache_lru_and_world_invalidation() -> None:
    cache = PathCache(max_entries=2)
    world = WorldKey("server", 0)
    key = cache.make_key(world, BlockPos(0, 64, 0), BlockPos(10, 64, 10))
    other = cache.make_key(WorldKey("server", -1), BlockPos(0, 64, 0), BlockPos(1, 64, 1))

    assert cache.get(key) is None
    cache.put(key, ["path"])
    cache.put(other, ["nether"])
    assert cache.get(key) == ["path"]
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1

    third = cache.make_key(world, BlockPos(1, 64, 1), BlockPos(2, 64, 2))
    cache.put(third, ["third"])
    assert len(cache) == 2
    assert cache.stats.evictions == 1
    assert cache.get(other) is None

    cache.put(key, ["path"])
    assert cache.invalidate_world(world) == 2
    assert len(cache) == 0


# ---------------------------------------------------------------------------- cluster


async def test_cluster_shares_chunks_ticks_and_broadcasts() -> None:
    server = FakeServer()
    await server.start()
    cluster = BotCluster(
        "127.0.0.1",
        port=server.port,
        use_srv=False,
        stagger=LoginStaggerPolicy(0.0, jitter=0.0),
        reconnect=False,
    )
    spawned: list[BotSpawnEvent] = []

    async def on_bot_spawn(event: BotSpawnEvent) -> None:
        spawned.append(event)

    cluster.event(on_bot_spawn)
    bots = cluster.spawn(3)
    try:
        cluster.start()
        await cluster.wait_until_ready(timeout=5.0)
        await asyncio.sleep(0.05)
        assert sorted(server.usernames) == ["Bot0", "Bot1", "Bot2"]
        assert all(bot.connected for bot in bots)

        chunks: list[ChunkLoadEvent] = []
        bots[0].events.subscribe(ChunkLoadEvent, chunks.append)
        server.send_play(
            "map_chunk",
            {
                "x": 0,
                "z": 0,
                "groundUp": True,
                "bitMap": 1 << 4,
                "chunkData": _chunk_payload(),
            },
        )
        await asyncio.sleep(0.2)
        assert len(chunks) == 1
        assert cluster.registry is not None
        stats = cluster.registry.stats()
        assert stats["chunks"] == 1
        assert stats["refs"] == 3

        tick = await asyncio.wait_for(
            bots[0].wait_for(PhysicsTickEvent, timeout=2.0), timeout=3.0
        )
        assert tick.tick >= 0

        sent = await cluster.broadcast("hello swarm")
        assert sent == 3
        await asyncio.sleep(0.1)
        assert server.chats.count("hello swarm") == 3

        metrics = cluster.metrics()
        assert metrics.total == 3
        assert metrics.connected == 3
        assert metrics.spawned == 3
        assert metrics.chunks == 1
        assert metrics.shared["refs"] == 3
        assert metrics.tick_groups == 1
        assert "mcflayer_cluster_bots 3" in metrics.to_prometheus()
        assert metrics.as_dict()["bots"] == 3
        assert len(spawned) == 3
    finally:
        await cluster.stop()
        await server.stop()
    assert len(cluster) == 0
    assert cluster.registry is not None
    assert cluster.registry.stats()["chunks"] == 0


async def test_cluster_applies_shared_block_update_only_once() -> None:
    server = FakeServer()
    await server.start()
    cluster = BotCluster(
        "127.0.0.1",
        port=server.port,
        use_srv=False,
        stagger=LoginStaggerPolicy(0.0, jitter=0.0),
        reconnect=False,
    )
    bots = cluster.spawn(3)
    try:
        cluster.start()
        await cluster.wait_until_ready(timeout=5.0)
        server.send_play(
            "map_chunk",
            {
                "x": 0,
                "z": 0,
                "groundUp": True,
                "bitMap": 1 << 4,
                "chunkData": _chunk_payload(),
            },
        )
        await asyncio.sleep(0.2)

        updates: list[tuple[str, BlockUpdateEvent]] = []
        for name, bot in cluster.bots.items():
            bot.events.subscribe(
                BlockUpdateEvent, lambda event, name=name: updates.append((name, event))
            )
        server.send_play(
            "block_change",
            {"location": {"x": 0, "y": 64, "z": 0}, "type": DIRT},
        )
        await asyncio.sleep(0.2)
        assert len(updates) == 1
        assert updates[0][1].state_id == DIRT
        assert bots[0].world.block_state_id(BlockPos(0, 64, 0)) == DIRT
    finally:
        await cluster.stop()
        await server.stop()


async def test_cluster_retires_kicked_bots_and_isolates_others() -> None:
    server = FakeServer(kick_after_join=True, kick_reason='{"text":"not welcome"}')
    await server.start()
    cluster = BotCluster(
        "127.0.0.1",
        port=server.port,
        use_srv=False,
        stagger=LoginStaggerPolicy(0.0, jitter=0.0),
        reconnect=False,
    )
    kicked: list[BotKickedEvent] = []

    async def on_bot_kicked(event: BotKickedEvent) -> None:
        kicked.append(event)

    cluster.event(on_bot_kicked)
    cluster.spawn(2)
    try:
        cluster.start()
        await asyncio.sleep(0.3)
        assert len(kicked) == 2
        assert len(cluster) == 0
        assert cluster.metrics().total == 0
    finally:
        await cluster.stop()
        await server.stop()


async def test_cluster_one_bot_closing_does_not_stop_the_other() -> None:
    server = FakeServer()
    await server.start()
    cluster = BotCluster(
        "127.0.0.1",
        port=server.port,
        use_srv=False,
        stagger=LoginStaggerPolicy(0.0, jitter=0.0),
        reconnect=False,
    )
    cluster.spawn(2)
    try:
        cluster.start()
        await cluster.wait_until_ready(timeout=5.0)
        await asyncio.sleep(0.05)
        await cluster.bot("Bot0").close()
        await asyncio.sleep(0.2)
        assert "Bot0" not in cluster.bots
        assert cluster.bot("Bot1").connected
        assert cluster.metrics().connected == 1
    finally:
        await cluster.stop()
        await server.stop()
