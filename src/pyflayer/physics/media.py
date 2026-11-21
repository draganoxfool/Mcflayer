"""Block media and friction sampled for physics (M4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from pyflayer.models.vec3 import BlockPos, Vec3

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
    except Exception:  # noqa: BLE001 - unloaded chunks are air for physics
        return ""
    return str(getattr(block, "name", "")).removeprefix("minecraft:")


def sample_medium(world: _WorldReader, position: Vec3, *, on_ground: bool) -> Medium:
    """Sample the blocks around ``position`` for water/lava/web/ladder and friction."""
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
        in_water="water" in names or "flowing_water" in names,
        in_lava="lava" in names or "flowing_lava" in names,
        in_web="web" in names,
        on_ladder="ladder" in names,
        slipperiness=_SLIPPERINESS.get(below_name, 0.6),
        speed_multiplier=_SPEED_MULTIPLIER.get(below_name, 1.0),
    )
