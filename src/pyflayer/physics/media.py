"""Block media and friction sampled for physics (M4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.physics.state import PLAYER_HEIGHT, PLAYER_WIDTH

__all__ = ["Medium", "sample_medium"]

# Vanilla slipperiness values for the blocks the 1.8 data set exposes. Everything else is 0.6.
_SLIPPERINESS = {
    "ice": 0.98,
    "packed_ice": 0.98,
    "slime": 0.8,
}
_SPEED_MULTIPLIER = {
    "soul_sand": 0.4,
}
_WATER_NAMES = {"water", "flowing_water"}
_LAVA_NAMES = {"lava", "flowing_lava"}


class _WorldReader(Protocol):
    def block_at(self, pos: BlockPos) -> object: ...


@dataclass(frozen=True, slots=True)
class Medium:
    """Environment sampled at the player's current position."""

    in_water: bool = False
    in_lava: bool = False
    in_web: bool = False
    on_ladder: bool = False
    slipperiness: float = 0.6
    speed_multiplier: float = 1.0


def _block_name(world: _WorldReader, pos: BlockPos) -> str:
    try:
        block = world.block_at(pos)
    except Exception:
        return ""
    return str(getattr(block, "name", "")).removeprefix("minecraft:")


def _fluid_overlap(world: _WorldReader, box: AABB, names: set[str]) -> bool:
    for x in range(math.floor(box.min_x), math.floor(box.max_x) + 1):
        for y in range(math.floor(box.min_y), math.floor(box.max_y) + 1):
            for z in range(math.floor(box.min_z), math.floor(box.max_z) + 1):
                pos = BlockPos(x, y, z)
                try:
                    block = world.block_at(pos)
                except Exception:
                    continue
                name = str(getattr(block, "name", "")).removeprefix("minecraft:")
                if name not in names:
                    continue
                metadata = int(getattr(block, "metadata", 0))
                level = 0 if metadata >= 8 else metadata & 0x7
                surface = y + 1.0 - (level + 1) / 9.0
                fluid_box = AABB(x, y, z, x + 1.0, surface, z + 1.0)
                if box.intersects(fluid_box):
                    return True
    return False


def sample_medium(world: _WorldReader, position: Vec3, *, on_ground: bool) -> Medium:
    """Sample the blocks around ``position`` for water/lava/web/ladder and friction."""
    box = AABB.from_center(position, PLAYER_WIDTH / 2, PLAYER_HEIGHT)
    feet = position.floored()
    mid = (position + Vec3(0.0, 0.9, 0.0)).floored()
    head = (position + Vec3(0.0, 1.5, 0.0)).floored()
    names = {_block_name(world, pos) for pos in (feet, mid, head)}

    below = BlockPos(
        math.floor(position.x),
        math.floor(position.y - (0.05 if on_ground else 0.01)),
        math.floor(position.z),
    )
    below_name = _block_name(world, below)
    return Medium(
        in_water=_fluid_overlap(world, box, _WATER_NAMES),
        in_lava=_fluid_overlap(world, box, _LAVA_NAMES),
        in_web="web" in names,
        on_ladder="ladder" in names,
        slipperiness=_SLIPPERINESS.get(below_name, 0.6),
        speed_multiplier=_SPEED_MULTIPLIER.get(below_name, 1.0),
    )
