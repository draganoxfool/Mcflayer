#!/usr/bin/env python3
"""Run the M4 physics engine on a small world and print the trajectory.

The world is one 16x16 chunk with a stone floor at Y=63, a stone-slab step from Z=8..11 at Y=64,
and a two-block wall at Z=14. The script walks forward, jumps, then walks into the wall.

    python examples/physics_demo.py
"""

from __future__ import annotations

from pyflayer.data import McData
from pyflayer.models import ChunkPos, Vec3
from pyflayer.physics import ControlState, PhysicsEngine, PlayerState
from pyflayer.world import ChunkColumn, World

STONE = 16
STONE_SLAB = 44 << 4


def build_world() -> World:
    world = World(McData.load("1.8.9"))
    column = ChunkColumn(ChunkPos(0, 0))
    for x in range(16):
        for z in range(16):
            column.apply_block_in_place(x, 63, z, STONE)
    for x in range(16):
        for z in range(8, 12):
            column.apply_block_in_place(x, 64, z, STONE_SLAB)
    for x in range(16):
        for y in (64, 65):
            column.apply_block_in_place(x, y, 14, STONE)
    world.apply_chunk(column)
    return world


def controls_for(tick: int) -> ControlState:
    if 5 <= tick < 30:
        return ControlState(forward=1, yaw=0)
    if tick == 30:
        return ControlState(forward=1, yaw=0, jump=True, sprint=True)
    if tick < 46:
        return ControlState(forward=1, yaw=0, sprint=True)
    if tick < 51:
        return ControlState()
    return ControlState(forward=1, yaw=0)


def main() -> None:
    world = build_world()
    engine = PhysicsEngine()
    state = PlayerState(Vec3(8.5, 64.0, 5.5), on_ground=True)
    peak_y = state.position.y
    first_wall_tick: int | None = None

    print(f"{'tick':>4}  {'x':>6} {'y':>7} {'z':>7}  {'vy':>8}  {'ground':>6}  medium")
    print("-" * 61)
    for tick in range(90):
        state = engine.step(state, controls_for(tick), world)
        peak_y = max(peak_y, state.position.y)

        if (
            state.on_ground
            and state.position.z >= 13.7 - 1e-9
            and abs(state.velocity.z) < 1e-9
            and first_wall_tick is None
        ):
            first_wall_tick = tick
        if tick % 5 == 0 or tick in {30, first_wall_tick}:
            medium = (
                "water"
                if state.in_water
                else "lava"
                if state.in_lava
                else "web"
                if state.in_web
                else "ladder"
                if state.on_ladder
                else "air"
            )
            print(
                f"{tick:>4}  {state.position.x:>6.2f} {state.position.y:>7.3f} "
                f"{state.position.z:>7.3f}  {state.velocity.y:>8.4f}  "
                f"{state.on_ground!s:>6}  {medium}"
            )

    print("-" * 61)
    print(f"jump peak Y       : {peak_y:.6f}")
    print(f"final position    : {state.position}")
    print(f"final on_ground   : {state.on_ground}")
    print(f"wall reached tick : {first_wall_tick}")
    print(f"final velocity    : {state.velocity}")


if __name__ == "__main__":
    main()
