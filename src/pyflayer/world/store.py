"""Refcounted chunk store for shared worlds (used by the swarm in M7).

A store is keyed by ``(server, dimension)``. Bots acquire a ref for every chunk they currently hold
and release it on unload or disconnect; the column is dropped when the last ref goes away. Duplicate
chunk arrivals from another bot do not decode or replace an existing column.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.world.chunk import ChunkColumn

__all__ = ["ChunkStore", "WorldKey"]


@dataclass(frozen=True, slots=True)
class WorldKey:
    """Identifies one world shared by a group of bots."""

    server: str
    dimension: int | str = 0


class ChunkStore:
    """Refcounted chunk storage with idempotent block updates."""

    __slots__ = ("_chunks", "_refs", "key")

    def __init__(self, key: WorldKey) -> None:
        self.key = key
        self._chunks: dict[ChunkPos, ChunkColumn] = {}
        self._refs: dict[ChunkPos, dict[int, int]] = {}

    def acquire(self, bot_id: int, pos: ChunkPos) -> ChunkColumn | None:
        """Add a ref for ``bot_id``; return the column if it is already loaded."""
        refs = self._refs.setdefault(pos, {})
        refs[bot_id] = refs.get(bot_id, 0) + 1
        return self._chunks.get(pos)

    def release(self, bot_id: int, pos: ChunkPos) -> bool:
        """Drop one ref; return ``True`` when the chunk was collected."""
        refs = self._refs.get(pos)
        if refs is None or bot_id not in refs:
            return False
        refs[bot_id] -= 1
        if refs[bot_id] <= 0:
            del refs[bot_id]
        if not refs:
            self._refs.pop(pos, None)
            self._chunks.pop(pos, None)
            return True
        return False

    def put(self, column: ChunkColumn, *, from_bot: int = 0) -> bool:
        """Store a decoded column unless an equivalent one is present.

        Returns ``True`` when the caller's data was inserted (i.e. it was the first copy).
        """
        existing = self._chunks.get(column.pos)
        if existing is not None and existing.version >= column.version:
            self.acquire(from_bot, column.pos)
            return False
        self._chunks[column.pos] = column
        self.acquire(from_bot, column.pos)
        return True

    def get(self, pos: ChunkPos) -> ChunkColumn | None:
        """Column at ``pos``."""
        return self._chunks.get(pos)

    def replace(self, column: ChunkColumn) -> None:
        """Store ``column`` without changing any refcount.

        Shared worlds use this when the same bot sends a newer copy of a chunk it already holds;
        :meth:`put` would add a second ref for the same owner.
        """
        self._chunks[column.pos] = column

    @property
    def chunks(self) -> dict[ChunkPos, ChunkColumn]:
        """Live chunk mapping (mutated only on the event loop)."""
        return self._chunks

    def release_all(self, bot_id: int) -> int:
        """Drop every ref held by ``bot_id``; return the number of chunks released."""
        released = 0
        for pos in list(self._refs):
            refs = self._refs[pos]
            if bot_id not in refs:
                continue
            del refs[bot_id]
            released += 1
            if not refs:
                del self._refs[pos]
                self._chunks.pop(pos, None)
        return released

    def stats(self) -> dict[str, int]:
        """Memory-oriented counters used by swarm metrics."""
        sections = 0
        estimated_bytes = 0
        for column in self._chunks.values():
            sections += column.section_count
            if column.biomes is not None:
                estimated_bytes += int(column.biomes.nbytes)
            for section in column.sections:
                if section is None:
                    continue
                blocks = section.blocks
                if blocks.indices is not None:
                    estimated_bytes += int(blocks.indices.nbytes)
                if blocks.palette is not None:
                    estimated_bytes += 8 * len(blocks.palette)
                if section.block_light is not None:
                    estimated_bytes += int(section.block_light.nbytes)
                if section.sky_light is not None:
                    estimated_bytes += int(section.sky_light.nbytes)
        return {
            "chunks": len(self._chunks),
            "refs": self.refcount,
            "sections": sections,
            "estimated_bytes": estimated_bytes,
        }

    def apply_block(self, pos: BlockPos, state_id: int, *, from_bot: int = 0) -> bool:
        """Apply a block update once; returns ``False`` for duplicates/unloaded chunks."""
        del from_bot
        column = self._chunks.get(pos.chunk)
        if column is None:
            return False
        return column.apply_block_in_place(pos.x & 15, pos.y, pos.z & 15, state_id)

    @property
    def refcount(self) -> int:
        """Total refs held across all chunks and bots."""
        return sum(sum(refs.values()) for refs in self._refs.values())

    def __len__(self) -> int:
        return len(self._chunks)

    def __repr__(self) -> str:
        return f"ChunkStore(key={self.key!r}, chunks={len(self._chunks)}, refs={self.refcount})"
