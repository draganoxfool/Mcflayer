"""Movement packet cadence and bot-owned physics ticks (M4)."""

from __future__ import annotations

import asyncio

import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.bot import Bot
from pyflayer.bot.movement import MovementTracker
from pyflayer.models import ChunkPos, Vec3
from pyflayer.testing import FakeServer
from pyflayer.world import ChunkColumn

STONE = 16  # (1 << 4) | 0


def test_no_packet_when_nothing_changes() -> None:
    tracker = MovementTracker()
    position = Vec3(1.5, 64.0, 2.5)
    tracker.reset(position, yaw=0.0, pitch=0.0, on_ground=True)

    assert tracker.observe(position, 0.0, 0.0, True) is None


def test_position_packet_when_squared_delta_exceeds_threshold() -> None:
    tracker = MovementTracker()
    tracker.reset(Vec3(0.0, 64.0, 0.0), 0.0, 0.0, True)

    packet = tracker.observe(Vec3(0.001, 64.0, 0.0), 0.0, 0.0, True)

    assert packet is not None
    assert packet.name == "position"
    assert packet.fields["x"] == pytest.approx(0.001)
    assert packet.fields["onGround"] is True


def test_look_packet_when_only_rotation_changes() -> None:
    tracker = MovementTracker()
    position = Vec3(1.5, 64.0, 2.5)
    tracker.reset(position, 0.0, 0.0, True)

    packet = tracker.observe(position, yaw=45.0, pitch=-10.0, on_ground=True)

    assert packet is not None
    assert packet.name == "look"
    assert packet.fields["yaw"] == pytest.approx(45.0)
    assert packet.fields["pitch"] == pytest.approx(-10.0)
    assert "x" not in packet.fields


def test_ground_flag_change_sends_flying() -> None:
    tracker = MovementTracker()
    position = Vec3(1.5, 64.0, 2.5)
    tracker.reset(position, 0.0, 0.0, True)

    packet = tracker.observe(position, 0.0, 0.0, on_ground=False)

    assert packet is not None
    assert packet.name == "flying"
    assert packet.fields == {"onGround": False}


def test_movement_and_rotation_use_position_look() -> None:
    tracker = MovementTracker()
    tracker.reset(Vec3(0.0, 64.0, 0.0), 0.0, 0.0, True)

    packet = tracker.observe(Vec3(0.1, 64.0, 0.0), 90.0, 0.0, True)

    assert packet is not None
    assert packet.name == "position_look"
    assert packet.fields["yaw"] == pytest.approx(90.0)
    assert packet.fields["x"] == pytest.approx(0.1)


def test_twenty_tick_reminder_sends_position() -> None:
    tracker = MovementTracker()
    position = Vec3(1.5, 64.0, 2.5)
    tracker.reset(position, 0.0, 0.0, True)

    packets = [tracker.observe(position, 0.0, 0.0, True) for _ in range(20)]

    assert all(packet is None for packet in packets[:19])
    assert packets[19] is not None
    assert packets[19].name == "position"


def test_confirm_18_echoes_position_and_resets_baseline() -> None:
    tracker = MovementTracker()
    tracker.reset(Vec3(0.0, 64.0, 0.0), 0.0, 0.0, True)
    teleported = Vec3(12.5, 70.0, -4.5)

    packet = tracker.confirm(teleported, yaw=30.0, pitch=5.0, on_ground=False)

    assert packet.name == "position_look"
    assert packet.fields["x"] == pytest.approx(12.5)
    assert tracker.observe(teleported, 30.0, 5.0, False) is None


def test_confirm_19_uses_teleport_id() -> None:
    tracker = MovementTracker()

    packet = tracker.confirm(
        Vec3(12.5, 70.0, -4.5), 30.0, 5.0, False, teleport_id=7
    )

    assert packet.name == "teleport_confirm"
    assert packet.fields == {"teleportId": 7}


def _floor_world_column() -> ChunkColumn:
    column = ChunkColumn(ChunkPos(0, 0))
    for x in range(16):
        for z in range(16):
            column.apply_block_in_place(x, 63, z, STONE)
    return column


async def test_bot_confirms_spawn_and_emits_movement_packets() -> None:
    async with FakeServer() as server:
        clock = FakeClock()
        bot = Bot(
            "Steve",
            host="127.0.0.1",
            port=server.port,
            use_srv=False,
            clock=clock,
        )
        await bot.connect()
        bot.world.apply_chunk(_floor_world_column())
        task = asyncio.create_task(bot.run())
        try:
            await asyncio.sleep(0.05)

            assert bot.physics_state is not None
            # The first tick answers the server position; 1.8 echoes the pose instead of
            # sending a teleport id.
            await clock.advance_async(0.05)
            await asyncio.sleep(0.01)
            bot.set_movement(forward=1.0, sprint=True)
            bot.look(yaw=270.0)
            for _ in range(6):
                await clock.advance_async(0.05)
                await asyncio.sleep(0.01)

            names = [packet.name for packet in server.received]
            assert "position_look" in names
            assert any(name in {"position", "position_look"} for name in names)
            actions = [
                packet.fields["actionId"]
                for packet in server.received
                if packet.name == "entity_action"
            ]
            assert "start_sprinting" in actions

            bot.stop_movement()
            for _ in range(3):
                await clock.advance_async(0.05)
                await asyncio.sleep(0.01)
            actions = [
                packet.fields["actionId"]
                for packet in server.received
                if packet.name == "entity_action"
            ]
            assert "stop_sprinting" in actions
            assert bot.on_ground
            assert bot.tick_driver is not None
            assert bot.tick_driver.tick >= 5
        finally:
            await bot.close()
            await asyncio.gather(task, return_exceptions=True)


async def test_server_position_sets_control_look_direction() -> None:
    """A spawn/teleport pose must drive the next physics tick's heading.

    Regression: ``_on_position`` updated ``bot.yaw``/``physics_state`` but not
    ``bot.controls``, so the physics loop kept using the constructor default (0, 0) and moved in
    the wrong direction on servers that spawn players facing elsewhere.
    """
    async with FakeServer() as server:
        bot = Bot("Steve", host="127.0.0.1", port=server.port, use_srv=False)
        await bot.connect()
        task = asyncio.create_task(bot.run())
        try:
            # FakeServer already sent a position at yaw 0; send an authoritative correction.
            server.send_play(
                "position",
                {
                    "x": 0.5,
                    "y": 64.0,
                    "z": 0.5,
                    "yaw": 90.0,
                    "pitch": -12.0,
                    "flags": 0,
                },
            )
            async with asyncio.timeout(2):
                while bot.controls.yaw != 90.0:
                    await asyncio.sleep(0.01)
            assert bot.yaw == 90.0
            assert bot.pitch == -12.0
            assert bot.controls.pitch == -12.0
        finally:
            await bot.close()
            await asyncio.gather(task, return_exceptions=True)


async def test_jump_is_consumed_by_exactly_one_tick() -> None:
    async with FakeServer() as server:
        clock = FakeClock()
        bot = Bot(
            "Steve",
            host="127.0.0.1",
            port=server.port,
            use_srv=False,
            clock=clock,
        )
        await bot.connect()
        bot.world.apply_chunk(_floor_world_column())
        task = asyncio.create_task(bot.run())
        try:
            await asyncio.sleep(0.05)
            # First tick confirms the spawn teleport; the next ones settle onto the floor.
            for _ in range(4):
                await clock.advance_async(0.05)
                await asyncio.sleep(0.01)
            assert bot.on_ground

            bot.jump()
            assert bot._jump_next
            await clock.advance_async(0.05)
            assert not bot._jump_next
            assert bot.physics_state is not None
            assert bot.physics_state.velocity.y > 0.0
        finally:
            await bot.close()
            await asyncio.gather(task, return_exceptions=True)
