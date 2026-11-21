"""Chunk columns.

A column owns up to 16 immutable sections plus biomes and block entities. Block writes replace the
section and bump ``version``; :meth:`copy` produces a cheap snapshot that later writes
cannot mutate.

Examples:
    >>> column = ChunkColumn(ChunkPos(0, 0))
    >>> column.block_state_id(0, 64, 0)
    0
    >>> column.with_block(0, 64, 0, 16).block_state_id(0, 64, 0)
    16
"""

from __future__ import annotations

import numpy as np

from pyflayer.errors import OutOfWorldBounds
from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.protocol.native.chunk_data import LegacyChunkData
from pyflayer.world.section import ChunkSection

__all__ = ["MAX_SECTIONS", "MIN_SECTIONS", "ChunkColumn"]

MIN_SECTIONS = 16
MAX_SECTIONS = 16


class ChunkColumn:
    """One 16x256x16 chunk column (1.8 layout)."""

    __slots__ = ("biomes", "block_entities", "height", "min_y", "pos", "sections", "version")

    def __init__(
        self,
        pos: ChunkPos,
        *,
        min_y: int = 0,
        height: int = 256,
        sections: list[ChunkSection | None] | None = None,
        biomes: np.ndarray | None = None,
        block_entities: dict[BlockPos, dict[str, object]] | None = None,
    ) -> None:
        self.pos = pos
        self.min_y = min_y
        self.height = height
        self.sections: list[ChunkSection | None] = (
            list(sections) if sections is not None else [None] * (height // 16)
        )
        self.biomes = biomes
        self.block_entities: dict[BlockPos, dict[str, object]] = dict(block_entities or {})
        self.version = 1

    @property
    def section_count(self) -> int:
        """Number of present sections."""
        return sum(1 for section in self.sections if section is not None)

    @property
    def non_air(self) -> int:
        """Total non-air blocks in the column."""
        return sum(section.non_air for section in self.sections if section is not None)

    def section_for_y(self, world_y: int) -> ChunkSection | None:
        """Section containing a world Y, or ``None`` when outside the column."""
        index = (world_y - self.min_y) >> 4
        if 0 <= index < len(self.sections):
            return self.sections[index]
        return None

    def block_state_id(self, local_x: int, world_y: int, local_z: int) -> int:
        """Legacy state id at local X/Z and world Y; absent sections are air."""
        _check_local(local_x, world_y, local_z, self.min_y, self.height)
        section = self.sections[(world_y - self.min_y) >> 4]
        if section is None:
            return 0
        return section.state_at(local_x, world_y & 15, local_z)

    def with_block(self, local_x: int, world_y: int, local_z: int, state_id: int) -> ChunkColumn:
        """Return a changed copy of this column.

        The original column is untouched; the section is replaced (ADR-6).
        """
        _check_local(local_x, world_y, local_z, self.min_y, self.height)
        index = (world_y - self.min_y) >> 4
        section = self.sections[index]
        if section is None:
            from pyflayer.world.palette import PalettedContainer

            section = ChunkSection(PalettedContainer.single(0), 0)
        new_section = section.with_state(local_x, world_y & 15, local_z, state_id)
        if new_section is section:
            return self
        clone = self.copy(keep_version=True)
        clone.sections[index] = new_section
        clone.version = self.version + 1
        return clone

    def apply_block_in_place(self, local_x: int, world_y: int, local_z: int, state_id: int) -> bool:
        """Mutate this column (world thread only). Returns ``False`` for a no-op."""
        _check_local(local_x, world_y, local_z, self.min_y, self.height)
        index = (world_y - self.min_y) >> 4
        section = self.sections[index]
        if section is None:
            from pyflayer.world.palette import PalettedContainer

            section = ChunkSection(PalettedContainer.single(0), 0)
        new_section = section.with_state(local_x, world_y & 15, local_z, state_id)
        if new_section is section:
            return False
        self.sections[index] = new_section
        self.version += 1
        return True

    def copy(self, *, keep_version: bool = False) -> ChunkColumn:
        """Shallow-copy the column; sections are immutable so they can be shared."""
        clone = ChunkColumn(
            self.pos,
            min_y=self.min_y,
            height=self.height,
            sections=self.sections,
            biomes=self.biomes,
            block_entities=self.block_entities,
        )
        clone.version = self.version if keep_version else 1
        return clone

    @classmethod
    def from_legacy(cls, pos: ChunkPos, data: LegacyChunkData) -> ChunkColumn:
        """Build a column from a decoded 1.8 chunk payload."""
        sections: list[ChunkSection | None] = [None] * (256 // 16)
        for index, states in data.sections.items():
            if not 0 <= index < len(sections):
                continue
            sections[index] = ChunkSection.from_legacy(
                states,
                block_light=data.block_light.get(index),
                sky_light=data.sky_light.get(index),
            )
        block_entities: dict[BlockPos, dict[str, object]] = {}
        for record in data.block_entities:
            local = (int(record.get("x", 0)), int(record.get("y", 0)), int(record.get("z", 0)))
            block_entities[BlockPos(pos.x * 16 + local[0], local[1], pos.z * 16 + local[2])] = (
                record
            )
        return cls(
            pos,
            sections=sections,
            biomes=data.biomes,
            block_entities=block_entities,
        )

    def with_legacy_update(self, data: LegacyChunkData) -> ChunkColumn:
        """Return a copy with the sections present in a partial 1.8 chunk update replaced.

        Sections absent from ``data`` keep their blocks and light, and the biomes/block entities are
        retained when the update does not carry new ones (``groundUp=False``).
        """
        sections = list(self.sections)
        for index, states in data.sections.items():
            if not 0 <= index < len(sections):
                continue
            previous = sections[index]
            sections[index] = ChunkSection.from_legacy(
                states,
                block_light=data.block_light.get(
                    index, previous.block_light if previous is not None else None
                ),
                sky_light=data.sky_light.get(
                    index, previous.sky_light if previous is not None else None
                ),
            )
        block_entities = dict(self.block_entities)
        for record in data.block_entities:
            local = (int(record.get("x", 0)), int(record.get("y", 0)), int(record.get("z", 0)))
            block_entities[
                BlockPos(self.pos.x * 16 + local[0], local[1], self.pos.z * 16 + local[2])
            ] = record
        clone = ChunkColumn(
            self.pos,
            min_y=self.min_y,
            height=self.height,
            sections=sections,
            biomes=data.biomes if data.biomes is not None else self.biomes,
            block_entities=block_entities,
        )
        clone.version = self.version + 1
        return clone

    def block_entity_at(self, pos: BlockPos) -> dict[str, object] | None:
        """Block-entity NBT at a world position, if any."""
        return self.block_entities.get(pos)

    def __repr__(self) -> str:
        return f"ChunkColumn(pos={self.pos}, sections={self.section_count}, non_air={self.non_air})"


def _check_local(local_x: int, world_y: int, local_z: int, min_y: int, height: int) -> None:
    if not (0 <= local_x < 16 and 0 <= local_z < 16):
        raise OutOfWorldBounds("local coordinate outside the chunk column", x=local_x, z=local_z)
    if not (min_y <= world_y < min_y + height):
        raise OutOfWorldBounds("Y outside the world height", y=world_y, min_y=min_y, height=height)
