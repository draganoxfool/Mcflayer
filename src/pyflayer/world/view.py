"""Read-only world views and snapshots.

A snapshot copies the chunk map and each column's section list. Because sections are immutable, the
copy is cheap and safe to read from a worker thread while the live world keeps updating (ADR-6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pyflayer.data.loader import McData
from pyflayer.errors import ChunkNotLoaded, OutOfWorldBounds
from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.world.block import BlockState
from pyflayer.world.chunk import ChunkColumn

__all__ = ["Bounds", "WorldSnapshot"]


class Bounds:
    """Optional inclusive block bounds used when snapshotting."""

    __slots__ = ("max_x", "max_y", "max_z", "min_x", "min_y", "min_z")

    def __init__(
        self, min_x: int, min_y: int, min_z: int, max_x: int, max_y: int, max_z: int
    ) -> None:
        self.min_x = min_x
        self.min_y = min_y
        self.min_z = min_z
        self.max_x = max_x
        self.max_y = max_y
        self.max_z = max_z

    def contains_chunk(self, pos: ChunkPos) -> bool:
        """True when the chunk overlaps the bounds."""
        return not (
            pos.x * 16 > self.max_x
            or pos.x * 16 + 15 < self.min_x
            or pos.z * 16 > self.max_z
            or pos.z * 16 + 15 < self.min_z
        )


class WorldSnapshot:
    """Immutable ``{ChunkPos: ChunkColumn}`` view implementing the reader contract."""

    __slots__ = ("_blocks", "chunks", "height", "mc", "min_y")

    def __init__(
        self,
        mc: McData,
        chunks: Mapping[ChunkPos, ChunkColumn],
        *,
        min_y: int = 0,
        height: int = 256,
    ) -> None:
        self.mc = mc
        self.chunks: dict[ChunkPos, ChunkColumn] = dict(chunks)
        self.min_y = min_y
        self.height = height
        self._blocks: dict[int, BlockState] = {}

    def is_loaded(self, pos: ChunkPos) -> bool:
        """True when the snapshot contains the chunk."""
        return pos in self.chunks

    def block_state_id(self, pos: BlockPos) -> int:
        """State id at ``pos``.

        Raises:
            ChunkNotLoaded: When the chunk was not in the snapshot.
            OutOfWorldBounds: When Y is outside the dimension.
        """
        column = self.chunks.get(pos.chunk)
        if column is None:
            raise ChunkNotLoaded("chunk not loaded", pos=pos)
        if not (self.min_y <= pos.y < self.min_y + self.height):
            raise OutOfWorldBounds("Y outside the world", y=pos.y)
        return column.block_state_id(pos.x & 15, pos.y, pos.z & 15)

    def block_state_id_or(self, pos: BlockPos, default: int) -> int:
        """State id or ``default`` for unloaded/out-of-bounds positions."""
        try:
            return self.block_state_id(pos)
        except (ChunkNotLoaded, OutOfWorldBounds):
            return default

    def block_at(self, pos: BlockPos) -> BlockState:
        """Resolved block state."""
        state_id = self.block_state_id(pos)
        state = self._blocks.get(state_id)
        if state is None:
            state = BlockState.from_legacy(state_id, self.mc)
            self._blocks[state_id] = state
        return state

    def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]:
        """Collision boxes of the block at ``pos`` (empty when unloaded)."""
        try:
            return self.block_at(pos).collision_boxes(self.mc)
        except (ChunkNotLoaded, OutOfWorldBounds):
            return ()

    def iter_columns(self) -> Iterable[ChunkColumn]:
        """Iterate the snapshot's columns."""
        return self.chunks.values()

    def __len__(self) -> int:
        return len(self.chunks)

    def __repr__(self) -> str:
        return f"WorldSnapshot(chunks={len(self.chunks)}, height={self.height})"
