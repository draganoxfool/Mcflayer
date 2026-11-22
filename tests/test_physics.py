from __future__ import annotations

import asyncio
import math
import random

import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.data import McData
from pyflayer.models import AABB, BlockPos, ChunkPos, Vec3
from pyflayer.physics import (
    ControlState,
    PhysicsEngine,
    PlayerState,
    TickDriver,
    move_box,
    sample_medium,
)
from pyflayer.world import ChunkColumn, World

MC = McData.load("1.8.9")
STONE = 16  # (1 << 4) | 0
STONE_SLAB = 44 << 4
WATER = 9 << 4
FLOWING_WATER = 8 << 4
LAVA = 10 << 4
FLOWING_LAVA = 11 << 4
OAK_STAIRS = (MC.blocks["oak_stairs"].id << 4) | 2  # bottom step, north-facing rise
LADDER = MC.blocks["ladder"].id << 4
SOUL_SAND = MC.blocks["soul_sand"].id << 4


def flat_world(
    *,
    wall_z: int | None = None,
    slab: bool = False,
    water: bool = False,
    water_state: int = WATER,
) -> World:
    world = World(MC)
    column = ChunkColumn(ChunkPos(0, 0))
    for x in range(16):
        for z in range(16):
            column.apply_block_in_place(x, 63, z, STONE)
    if wall_z is not None:
        for x in range(16):
            for y in (64, 65):
                column.apply_block_in_place(x, y, wall_z, STONE)
    if slab:
        for x in range(16):
            for z in range(8, 12):
                column.apply_block_in_place(x, 64, z, STONE_SLAB)
    if water:
        for x in range(16):
            for z in range(16):
                for y in (64, 65):
                    column.apply_block_in_place(x, y, z, water_state)
    world.apply_chunk(column)
    return world


def platform_world(*, end_x: int = 16, end_z: int = 10) -> World:
    world = World(MC)
    column = ChunkColumn(ChunkPos(0, 0))
    for x in range(end_x):
        for z in range(end_z):
            column.apply_block_in_place(x, 63, z, STONE)
    world.apply_chunk(column)
    return world


def test_fall_lands_on_floor() -> None:
    engine = PhysicsEngine()
    state = PlayerState(Vec3(8.5, 66.0, 8.5))

    for _ in range(10):
        state = engine.step(state, ControlState(), flat_world())

    assert state.position.y == pytest.approx(64.0)
    assert state.on_ground
    # Vanilla keeps the damped gravity value after the ground collision.
    assert state.velocity.y == pytest.approx(-0.0784)


def test_walk_matches_reference_terminal_velocity() -> None:
    engine = PhysicsEngine()
    world = flat_world()
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)

    for _ in range(20):
        state = engine.step(state, ControlState(forward=1, yaw=0), world)

    # prismarine-physics 1.8.9 reaches 0.11785842372264366 blocks/tick.
    assert state.velocity.z == pytest.approx(0.11785842372264366, abs=1e-6)
    assert state.position.z > 8.5
    assert state.on_ground


def test_sprint_is_faster_than_walk_and_sneak_is_slower() -> None:
    engine = PhysicsEngine()
    world = flat_world()

    def run(**controls: object) -> PlayerState:
        state = PlayerState(Vec3(2.5, 64.0, 2.5), on_ground=True)
        for _ in range(20):
            state = engine.step(state, ControlState(forward=1, yaw=0, **controls), world)
        return state

    walk = run()
    sprint = run(sprint=True)
    sneak = run(sneak=True)
    assert sprint.velocity.z > walk.velocity.z > sneak.velocity.z


def test_sneaking_stops_at_straight_platform_edge() -> None:
    engine = PhysicsEngine()
    world = platform_world()
    state = PlayerState(Vec3(5.5, 64.0, 8.5), on_ground=True)

    for _ in range(40):
        state = engine.step(state, ControlState(forward=1, sneak=True, yaw=0), world)

    assert state.position.z <= 10.3
    assert state.position.z > 10.0
    assert state.on_ground


def test_sneaking_stops_at_diagonal_platform_corner() -> None:
    engine = PhysicsEngine()
    world = platform_world(end_x=10)
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)

    for _ in range(40):
        state = engine.step(
            state,
            ControlState(forward=1, strafe=1, sneak=True, yaw=0),
            world,
        )

    assert state.position.x <= 10.3
    assert state.position.z <= 10.3
    assert state.position.x > 10.0
    assert state.position.z > 10.0
    assert state.on_ground


def test_jump_arc_matches_reference_engine() -> None:
    engine = PhysicsEngine()
    world = flat_world()
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)

    state = engine.step(state, ControlState(jump=True), world)
    heights = [state.position.y]
    for _ in range(15):
        state = engine.step(state, ControlState(), world)
        heights.append(state.position.y)

    assert max(heights) == pytest.approx(65.25220334025373, abs=1e-6)
    assert state.position.y == pytest.approx(64.0)
    assert state.on_ground


def test_wall_stops_horizontal_motion_and_does_not_shrink_hitbox() -> None:
    engine = PhysicsEngine()
    world = flat_world(wall_z=10)
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)

    for _ in range(40):
        state = engine.step(state, ControlState(forward=1, yaw=0), world)

    assert state.position.z == pytest.approx(9.7)
    assert state.velocity.z == pytest.approx(0.0)
    assert state.box.max_z - state.box.min_z == pytest.approx(0.6)
    assert state.position.y == pytest.approx(64.0)


@pytest.mark.parametrize(
    ("start_z", "amount", "expected_delta"),
    [(8.5, 5.0, 1.2), (12.5, -5.0, -1.2)],
)
def test_large_motion_stops_at_wall_in_both_directions(
    start_z: float, amount: float, expected_delta: float
) -> None:
    world = flat_world(wall_z=10)
    box = AABB.from_center(Vec3(8.5, 64.0, start_z), 0.3, 1.8)

    result = move_box(box, Vec3(0.0, 0.0, amount), world, can_step=False)

    assert result.delta.z == pytest.approx(expected_delta)
    assert result.hit_z
    assert not result.box.intersects(AABB(8.0, 64.0, 10.0, 9.0, 66.0, 11.0))


def test_large_motion_stops_at_thin_collision_shape() -> None:
    class ThinShapeWorld:
        def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]:
            if pos == BlockPos(0, 0, 4):
                return (AABB(0.0, 0.0, 0.25, 1.0, 1.0, 0.35),)
            return ()

    box = AABB.from_center(Vec3(0.5, 0.1, 1.5), 0.2, 0.8)
    result = move_box(box, Vec3(0.0, 0.0, 5.0), ThinShapeWorld(), can_step=False)

    assert result.delta.z == pytest.approx(2.55)
    assert result.hit_z
    assert result.box.max_z == pytest.approx(4.25)


def test_slab_step_up() -> None:
    engine = PhysicsEngine()
    world = flat_world(slab=True)
    state = PlayerState(Vec3(8.5, 64.0, 5.5), on_ground=True)

    for _ in range(15):
        state = engine.step(state, ControlState(forward=1, yaw=0), world)

    assert state.position.y == pytest.approx(64.5)
    assert state.position.z > 8.0
    assert state.on_ground


def test_water_sets_flag_and_slows_fall() -> None:
    engine = PhysicsEngine()
    world = flat_world(water=True)
    state = PlayerState(Vec3(8.5, 65.5, 8.5))

    state = engine.step(state, ControlState(), world)

    assert state.in_water
    assert state.velocity.y > -0.5


def test_flowing_water_sets_flag() -> None:
    engine = PhysicsEngine()
    world = flat_world(water=True, water_state=FLOWING_WATER)
    state = PlayerState(Vec3(8.5, 65.5, 8.5))

    state = engine.step(state, ControlState(), world)

    assert state.in_water
    assert state.velocity.y > -0.5


def test_fluid_sampling_detects_partial_horizontal_aabb_overlap() -> None:
    world = flat_world()
    _column(world).apply_block_in_place(0, 64, 2, WATER)

    medium = sample_medium(world, Vec3(1.25, 64.2, 2.5), on_ground=False)

    assert medium.in_water


def test_fluid_sampling_respects_legacy_surface_height() -> None:
    world = flat_world()
    _column(world).apply_block_in_place(2, 64, 2, WATER)

    overlapping = sample_medium(world, Vec3(2.5, 64.85, 2.5), on_ground=False)
    above_surface = sample_medium(world, Vec3(2.5, 64.90, 2.5), on_ground=False)

    assert overlapping.in_water
    assert not above_surface.in_water


@pytest.mark.parametrize("lava_state", [LAVA, FLOWING_LAVA])
def test_lava_sets_flag_and_slows_fall(lava_state: int) -> None:
    engine = PhysicsEngine()
    world = flat_world(water=True, water_state=lava_state)
    state = PlayerState(Vec3(8.5, 65.5, 8.5))

    state = engine.step(state, ControlState(), world)

    assert state.in_lava
    assert state.velocity.y > -0.5


async def test_tick_driver_uses_absolute_deadlines() -> None:
    clock = FakeClock()
    seen: list[tuple[int, float]] = []

    async def callback(tick: int) -> None:
        seen.append((tick, clock.monotonic()))

    driver = TickDriver(clock)
    task = asyncio.create_task(driver.run(callback))
    await asyncio.sleep(0)

    for _ in range(3):
        await clock.advance_async(0.05)

    driver.stop()
    await clock.advance_async(0.05)
    await task

    assert [tick for tick, _ in seen] == [0, 1, 2]
    assert [when for _, when in seen] == pytest.approx([0.05, 0.10, 0.15])
    assert driver.measured_tps == pytest.approx(20.0)
    assert driver.jitter == pytest.approx(0.0, abs=1e-9)
    assert driver.jitter_p99_ms == pytest.approx(0.0, abs=1e-9)
    assert driver.catch_up_ticks == 0
    assert driver.dropped_ticks == 0


async def test_tick_driver_caps_catch_up_and_records_drops() -> None:
    clock = FakeClock()
    seen: list[tuple[int, float]] = []

    async def callback(tick: int) -> None:
        seen.append((tick, clock.monotonic()))
        if tick == 2:
            # Simulate a 500 ms stall inside one tick.
            clock.advance(0.5)

    driver = TickDriver(clock, max_catch_up=2)
    task = asyncio.create_task(driver.run(callback))
    await asyncio.sleep(0)

    await clock.advance_async(0.15)
    for _ in range(20):
        await asyncio.sleep(0)

    driver.stop()
    await clock.advance_async(0.1)
    await task

    assert driver.dropped_ticks > 0
    assert driver.catch_up_ticks <= driver.max_catch_up + 2
    assert driver.catch_up_events >= 1
    # The loop is still monotonic and never runs more than a couple of late ticks back to back.
    assert [tick for tick, _ in seen] == list(range(len(seen)))


def _column(world: World) -> ChunkColumn:
    return world.chunks[ChunkPos(0, 0)]


def _assert_outside_solids(world: World, state: PlayerState) -> None:
    box = state.box
    for bx in range(math.floor(box.min_x), math.floor(box.max_x) + 1):
        for by in range(math.floor(box.min_y), math.floor(box.max_y) + 1):
            for bz in range(math.floor(box.min_z), math.floor(box.max_z) + 1):
                for local in world.collision_boxes(BlockPos(bx, by, bz)):
                    block = AABB(
                        local.min_x + bx,
                        local.min_y + by,
                        local.min_z + bz,
                        local.max_x + bx,
                        local.max_y + by,
                        local.max_z + bz,
                    )
                    assert not box.intersects(block), (
                        f"player at {state.position} intersects solid {block}"
                    )


def _has_support(world: World, state: PlayerState) -> bool:
    box = state.box
    for bx in range(math.floor(box.min_x), math.floor(box.max_x) + 1):
        for bz in range(math.floor(box.min_z), math.floor(box.max_z) + 1):
            for by in range(math.floor(state.position.y - 1.0), math.floor(state.position.y) + 1):
                for local in world.collision_boxes(BlockPos(bx, by, bz)):
                    if abs(by + local.max_y - state.position.y) > 1e-6:
                        continue
                    if (
                        bx + local.max_x > box.min_x
                        and bx + local.min_x < box.max_x
                        and bz + local.max_z > box.min_z
                        and bz + local.min_z < box.max_z
                    ):
                        return True
    return False


def test_stairs_step_up() -> None:
    world = flat_world()
    column = _column(world)
    for x in range(16):
        column.apply_block_in_place(x, 64, 10, OAK_STAIRS)

    engine = PhysicsEngine()
    state = PlayerState(Vec3(8.5, 64.0, 5.5), on_ground=True)
    heights: list[float] = []
    for _ in range(40):
        state = engine.step(state, ControlState(forward=1, yaw=0), world)
        _assert_outside_solids(world, state)
        heights.append(state.position.y)

    assert max(heights) >= 64.5
    assert state.position.z > 10.0


def test_ladder_climbs_when_pushing_into_it() -> None:
    world = flat_world()
    column = _column(world)
    for y in (64, 65, 66):
        column.apply_block_in_place(8, y, 8, LADDER)

    engine = PhysicsEngine()
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)
    heights: list[float] = []
    saw_ladder = False
    for _ in range(20):
        state = engine.step(state, ControlState(forward=1, yaw=0), world)
        _assert_outside_solids(world, state)
        heights.append(state.position.y)
        saw_ladder = saw_ladder or state.on_ladder

    assert saw_ladder
    assert max(heights) > 65.0


def test_sneaking_holds_position_on_ladder() -> None:
    world = flat_world()
    column = _column(world)
    for y in (64, 65, 66):
        column.apply_block_in_place(8, y, 8, LADDER)

    engine = PhysicsEngine()
    state = PlayerState(Vec3(8.5, 65.0, 8.5), velocity=Vec3(0.0, -0.5, 0.0))
    state = engine.step(state, ControlState(sneak=True), world)

    assert state.on_ladder
    assert state.position.y == pytest.approx(65.0)
    assert state.velocity.y >= 0.0


def test_soul_sand_slows_walking() -> None:
    stone_world = flat_world()
    soul_world = flat_world()
    column = _column(soul_world)
    for x in range(16):
        for z in range(16):
            column.apply_block_in_place(x, 63, z, SOUL_SAND)

    engine = PhysicsEngine()

    def walk(world: World) -> float:
        state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)
        for _ in range(20):
            state = engine.step(state, ControlState(forward=1, yaw=0), world)
        return state.velocity.z

    stone_speed = walk(stone_world)
    soul_speed = walk(soul_world)
    assert 0.0 < soul_speed < stone_speed * 0.5


def test_fuzzed_controls_never_enter_solid_blocks() -> None:
    world = flat_world()
    column = _column(world)
    for x in range(16):
        for y in (64, 65):
            column.apply_block_in_place(x, y, 0, STONE)
            column.apply_block_in_place(x, y, 15, STONE)
    for z in range(1, 15):
        for y in (64, 65):
            column.apply_block_in_place(0, y, z, STONE)
            column.apply_block_in_place(15, y, z, STONE)

    engine = PhysicsEngine()
    rng = random.Random(20261121)
    state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)
    yaw = 0.0

    for tick in range(300):
        if tick % 7 == 0:
            yaw = rng.uniform(-180.0, 180.0)
        state = engine.step(
            state,
            ControlState(
                forward=1.0,
                strafe=rng.choice((-1.0, 0.0, 1.0)),
                jump=rng.random() < 0.08,
                sprint=rng.random() < 0.6,
                sneak=rng.random() < 0.08,
                yaw=yaw,
            ),
            world,
        )
        _assert_outside_solids(world, state)
        assert 0.0 <= state.position.y <= 200.0
        if state.on_ground:
            assert _has_support(world, state), f"no support at tick {tick}: {state.position}"


async def test_tick_driver_is_cancel_safe() -> None:
    clock = FakeClock()

    async def callback(_: int) -> None:
        return

    driver = TickDriver(clock)
    task = asyncio.create_task(driver.run(callback))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clock.pending == 0
