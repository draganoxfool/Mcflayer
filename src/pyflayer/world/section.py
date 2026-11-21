"""A 16x16x16 chunk section.

Index order is ``(y << 8) | (z << 4) | x`` (YZX), matching the wire layout and the architecture.
Sections are immutable: changing a block replaces the section object inside its column, which keeps
world snapshots cheap and safe to read from worker threads (ADR-6).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pyflayer.errors import OutOfWorldBounds
from pyflayer.world.palette import PalettedContainer

__all__ = ["ChunkSection", "SECTION_SIZE", "section_index"]

SECTION_SIZE = 4096


def section_index(x: int, y: int, z: int) -> int:
    """Index of a local block inside its section (YZX order)."""
    return (y << 8) | (z << 4) | x


@dataclass(frozen=True, slots=True)
class ChunkSection:
    """One immutable section of a chunk column."""

    blocks: PalettedContainer
    non_air: int = 0
    block_light: np.ndarray | None = None
    sky_light: np.ndarray | None = None

    @classmethod
    def from_legacy(
        cls,
        states: np.ndarray,
        *,
        block_light: np.ndarray | None = None,
        sky_light: np.ndarray | None = None,
    ) -> ChunkSection:
        """Build from a 1.8 ``uint16`` state array."""
        if states.size != SECTION_SIZE:
            raise OutOfWorldBounds(
                "legacy section must have 4096 blocks", size=int(states.size)
            )
        non_air = int(np.count_nonzero(states >> 4))
        return cls(PalettedContainer.from_legacy(states), non_air, block_light, sky_light)

    def state_at(self, x: int, y: int, z: int) -> int:
        """Legacy state id at local coordinates."""
        return self.blocks.get(section_index(x, y, z))

    def with_state(self, x: int, y: int, z: int, state_id: int) -> ChunkSection:
        """Return a copy with one block changed."""
        index = section_index(x, y, z)
        old = self.blocks.get(index)
        if old == state_id:
            return self
        blocks = self.blocks.with_set(index, state_id)
        delta = (1 if (state_id >> 4) else 0) - (1 if (old >> 4) else 0)
        return ChunkSection(blocks, self.non_air + delta, self.block_light, self.sky_light)

    def states(self) -> np.ndarray:
        """Materialized ``uint16`` state array."""
        return self.blocks.to_array()

    def block_light_at(self, x: int, y: int, z: int) -> int:
        """Block light nibble at local coordinates, 0 when light is absent."""
        return _light_at(self.block_light, x, y, z)

    def sky_light_at(self, x: int, y: int, z: int) -> int:
        """Sky light nibble at local coordinates, 0 when light is absent."""
        return _light_at(self.sky_light, x, y, z)


def _light_at(light: np.ndarray | None, x: int, y: int, z: int) -> int:
    if light is None:
        return 0
    index = (y << 8) | (z << 4) | x
    byte = int(light[index >> 1])
    return (byte & 0x0F) if index % 2 == 0 else (byte >> 4) & 0x0F
