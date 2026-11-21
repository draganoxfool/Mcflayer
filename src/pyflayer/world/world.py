"""Mutable world for one dimension.

The world owns a ``{ChunkPos: ChunkColumn}`` map and only mutates on the event loop. Reads go
through :class:`~pyflayer.world.view.WorldSnapshot` for worker threads.

Examples:
    >>> world = World(McData.load("1.8.9"))
    >>> world.block_state_id_or(BlockPos(0, 64, 0), -1)
    -1
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

import numpy as np

from pyflayer.data.loader import McData
from pyflayer.errors import ChunkNotLoaded, OutOfWorldBounds
from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import BlockPos, ChunkPos, Vec3
from pyflayer.world.block import BlockState
from pyflayer.world.chunk import ChunkColumn
from pyflayer.world.raycast import RayHit, raycast
from pyflayer.world.section import ChunkSection
from pyflayer.world.view import Bounds, WorldSnapshot

__all__ = ["World"]


class World:
    """Mutable world state for one dimension."""

    __slots__ = ("_blocks", "chunks", "dimension", "height", "mc", "min_y")

    def __init__(
        self,
        mc: McData,
        *,
        min_y: int = 0,
        height: int = 256,
        dimension: int | str = 0,
    ) -> None:
        self.mc = mc
        self.chunks: dict[ChunkPos, ChunkColumn] = {}
        self.min_y = min_y
        self.height = height
        self.dimension = dimension
        self._blocks: dict[int, BlockState] = {}

    # ------------------------------------------------------------------ chunk lifecycle
    def apply_chunk(self, column: ChunkColumn) -> None:
        """Insert or replace a chunk column."""
        self.chunks[column.pos] = column

    def unload_chunk(self, pos: ChunkPos) -> ChunkColumn | None:
        """Remove and return a chunk, if loaded."""
        return self.chunks.pop(pos, None)

    def is_loaded(self, pos: ChunkPos) -> bool:
        """True when the chunk column is loaded."""
        return pos in self.chunks

    def clear(self) -> None:
        """Drop every chunk (dimension change, respawn, disconnect)."""
        self.chunks.clear()

    # ------------------------------------------------------------------ block reads
    def block_state_id(self, pos: BlockPos) -> int:
        """State id at ``pos``.

        Raises:
            ChunkNotLoaded: When the column is absent.
            OutOfWorldBounds: When Y is outside the world height.
        """
        column = self.chunks.get(pos.chunk)
        if column is None:
            raise ChunkNotLoaded("chunk not loaded", pos=pos)
        if not (self.min_y <= pos.y < self.min_y + self.height):
            raise OutOfWorldBounds("Y outside the world", y=pos.y, min_y=self.min_y)
        return column.block_state_id(pos.x & 15, pos.y, pos.z & 15)

    def block_state_id_or(self, pos: BlockPos, default: int) -> int:
        """State id or ``default`` when the position is unloaded/out of bounds."""
        try:
            return self.block_state_id(pos)
        except (ChunkNotLoaded, OutOfWorldBounds):
            return default

    def block_at(self, pos: BlockPos) -> BlockState:
        """Resolved block state (cached per state id)."""
        state_id = self.block_state_id(pos)
        state = self._blocks.get(state_id)
        if state is None:
            state = BlockState.from_legacy(state_id, self.mc)
            self._blocks[state_id] = state
        return state

    def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]:
        """Collision boxes of the block at ``pos``."""
        try:
            return self.block_at(pos).collision_boxes(self.mc)
        except (ChunkNotLoaded, OutOfWorldBounds):
            return ()

    def block_entity_at(self, pos: BlockPos) -> dict[str, object] | None:
        """Block-entity NBT at a position."""
        column = self.chunks.get(pos.chunk)
        return None if column is None else column.block_entity_at(pos)

    def section_at(self, pos: BlockPos) -> ChunkSection | None:
        """Section containing ``pos``, if present."""
        column = self.chunks.get(pos.chunk)
        return None if column is None else column.section_for_y(pos.y)

    # ------------------------------------------------------------------ block writes
    def set_block_state(
        self, pos: BlockPos, state_id: int, *, source: object | None = None
    ) -> bool:
        """Set one block. Returns ``False`` for a no-op or an unloaded chunk."""
        del source
        column = self.chunks.get(pos.chunk)
        if column is None:
            return False
        if not (self.min_y <= pos.y < self.min_y + self.height):
            return False
        return column.apply_block_in_place(pos.x & 15, pos.y, pos.z & 15, int(state_id))

    def apply_multi_block_change(
        self, chunk_pos: ChunkPos, changes: Sequence[tuple[int, int, int, int]]
    ) -> list[tuple[BlockPos, int, int]]:
        """Apply ``(local_x, y, local_z, state_id)`` changes; return ``(pos, old, new)``."""
        column = self.chunks.get(chunk_pos)
        if column is None:
            return []
        applied: list[tuple[BlockPos, int, int]] = []
        for local_x, y, local_z, state_id in changes:
            if not (self.min_y <= y < self.min_y + self.height):
                continue
            world_pos = BlockPos(chunk_pos.x * 16 + local_x, y, chunk_pos.z * 16 + local_z)
            old = column.block_state_id(local_x, y, local_z)
            if old == state_id:
                continue
            if column.apply_block_in_place(local_x, y, local_z, state_id):
                applied.append((world_pos, old, int(state_id)))
        return applied

    # ------------------------------------------------------------------ queries
    def find_blocks(
        self,
        matching: str | int | Callable[[int], bool],
        *,
        within: float = 32.0,
        around: Vec3 | BlockPos | None = None,
        count: int = 1,
    ) -> list[BlockPos]:
        """Find the nearest matching blocks within ``within`` blocks of ``around``.

        ``matching`` may be a block name, an exact state id or a predicate over state ids.
        """
        if count <= 0:
            return []
        center = _as_vec3(around)
        radius_chunks = max(1, math.ceil(within / 16.0))
        center_chunk = center.floored().chunk
        if isinstance(matching, str):
            block = self.mc.blocks.get(matching)
            if block is None:
                return []
            block_id = block.id

            def predicate(states: np.ndarray) -> np.ndarray:
                return (states >> 4) == block_id
        elif isinstance(matching, int):
            state_id = matching

            def predicate(states: np.ndarray) -> np.ndarray:
                return states == state_id
        else:
            user_predicate = matching
            predicate = np.vectorize(lambda value: bool(user_predicate(int(value))))

        found: list[tuple[float, BlockPos]] = []
        for dx in range(-radius_chunks, radius_chunks + 1):
            for dz in range(-radius_chunks, radius_chunks + 1):
                column = self.chunks.get(ChunkPos(center_chunk.x + dx, center_chunk.z + dz))
                if column is None:
                    continue
                for index, section in enumerate(column.sections):
                    if section is None or section.non_air == 0:
                        continue
                    states = section.states()
                    hits = np.flatnonzero(predicate(states))
                    for raw_index in hits:
                        local_index = int(raw_index)
                        local_x = local_index & 15
                        local_z = (local_index >> 4) & 15
                        y = column.min_y + index * 16 + (local_index >> 8)
                        pos = BlockPos(column.pos.x * 16 + local_x, y, column.pos.z * 16 + local_z)
                        distance = center.distance_to(pos.to_vec3())
                        if distance <= within:
                            found.append((distance, pos))
        found.sort(key=lambda item: (item[0], item[1]))
        return [pos for _distance, pos in found[:count]]

    def raycast(
        self,
        origin: Vec3,
        direction: Vec3,
        max_dist: float,
        *,
        include_fluids: bool = False,
    ) -> RayHit | None:
        """Voxel raycast over collision shapes (DDA)."""
        return raycast(self, origin, direction, max_dist, include_fluids=include_fluids)

    # ------------------------------------------------------------------ snapshots
    def snapshot(self, bounds: Bounds | None = None) -> WorldSnapshot:
        """Copy the chunk map (columns share immutable sections)."""
        chunks = {
            pos: column.copy()
            for pos, column in self.chunks.items()
            if bounds is None or bounds.contains_chunk(pos)
        }
        return WorldSnapshot(self.mc, chunks, min_y=self.min_y, height=self.height)

    def iter_columns(self) -> Iterable[ChunkColumn]:
        """Iterate loaded columns."""
        return self.chunks.values()

    def __len__(self) -> int:
        return len(self.chunks)

    def __repr__(self) -> str:
        return f"World(dimension={self.dimension!r}, chunks={len(self.chunks)})"


def _as_vec3(value: Vec3 | BlockPos | None) -> Vec3:
    if value is None:
        return Vec3(0.0, 0.0, 0.0)
    if isinstance(value, BlockPos):
        return value.to_vec3()
    return value
