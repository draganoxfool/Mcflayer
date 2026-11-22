"""Shared chunk storage for co-located bots.

Bots in one cluster usually see the same world. Decoding and storing one copy per ``(server,
dimension)`` keeps chunk memory sublinear in the number of bots: the first bot's copy is inserted,
later bots only add a reference, and the column is collected when the last bot releases it.

Each bot gets its own :class:`SharedWorld` *view*. A view only reports the chunks that bot currently
references, so sharing never exposes a chunk a bot has not received from its own connection.

Examples:
    >>> registry = SharedWorldRegistry(McData.load("1.8.9"), server="play.example.net:25565")
    >>> first = registry.view(bot_id=1)
    >>> second = registry.view(bot_id=2)
    >>> first.is_loaded(ChunkPos(0, 0))
    False
    >>> registry.release(first)
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence

from pyflayer.data.loader import McData
from pyflayer.errors import ChunkNotLoaded
from pyflayer.models.vec3 import BlockPos, ChunkPos, Vec3
from pyflayer.world.chunk import ChunkColumn
from pyflayer.world.store import ChunkStore, WorldKey
from pyflayer.world.view import Bounds, WorldSnapshot
from pyflayer.world.world import World

__all__ = ["SharedWorld", "SharedWorldRegistry"]


class SharedWorld(World):
    """A bot's read/write view over a shared :class:`ChunkStore`.

    The view keeps the refcount for every chunk this bot has received. Reads of chunks the bot has
    not acquired raise :class:`~pyflayer.errors.ChunkNotLoaded` (or return the supplied default),
    even when another bot has already loaded that chunk.

    Args:
        mc: Minecraft data for block resolution.
        registry: Registry that owns the underlying stores.
        server: Server key shared by the cluster (``host:port``).
        dimension: Initial dimension.
        bot_id: Stable per-bot refcount owner.
    """

    def __init__(
        self,
        mc: McData,
        registry: SharedWorldRegistry,
        *,
        server: str,
        dimension: int | str = 0,
        bot_id: int = 0,
    ) -> None:
        self._registry = registry
        self._server = server
        self._bot_id = bot_id
        self._held: set[ChunkPos] = set()
        self._store = registry.store(dimension)
        super().__init__(mc, dimension=dimension)
        # World methods read ``self.chunks``; aliasing the store's live mapping means a column
        # inserted by any bot becomes visible without copying. Access is still gated by ``_held``.
        self.chunks = self._store.chunks

    # ------------------------------------------------------------------ identity
    @property
    def bot_id(self) -> int:
        """Refcount owner of this view."""
        return self._bot_id

    @property
    def store(self) -> ChunkStore:
        """The backing store for the current dimension."""
        return self._store

    @property
    def held(self) -> frozenset[ChunkPos]:
        """Chunks currently referenced by this bot."""
        return frozenset(self._held)

    # ------------------------------------------------------------------ chunk lifecycle
    def apply_chunk(self, column: ChunkColumn) -> None:
        """Insert or refresh ``column`` and hold one ref for this bot."""
        if column.pos in self._held:
            self._store.replace(column)
        else:
            self._held.add(column.pos)
            self._store.put(column, from_bot=self._bot_id)

    def unload_chunk(self, pos: ChunkPos) -> ChunkColumn | None:
        """Release this bot's ref and return the column when it is still loaded."""
        if pos not in self._held:
            return None
        self._held.discard(pos)
        self._store.release(self._bot_id, pos)
        return self._store.get(pos)

    def clear(self) -> None:
        """Release every ref held by this bot (respawn, disconnect, dimension change)."""
        for pos in list(self._held):
            self._store.release(self._bot_id, pos)
        self._held.clear()

    def set_dimension(self, dimension: int | str) -> None:
        """Release the old dimension's refs and rebind to the new dimension's store."""
        if dimension == self.dimension:
            return
        self.clear()
        self.dimension = dimension
        self._store = self._registry.store(dimension)
        self.chunks = self._store.chunks

    def detach(self) -> None:
        """Drop every ref; equivalent to :meth:`clear` (cluster teardown)."""
        self.clear()

    # ------------------------------------------------------------------ reads
    def is_loaded(self, pos: ChunkPos) -> bool:
        """True only when *this* bot currently references the chunk."""
        return pos in self._held and pos in self._store.chunks

    def block_state_id(self, pos: BlockPos) -> int:
        """State id at ``pos`` from a chunk this bot references.

        Raises:
            ChunkNotLoaded: When this bot has not received the column.
        """
        if pos.chunk not in self._held:
            raise ChunkNotLoaded("chunk not referenced by this bot", pos=pos)
        return super().block_state_id(pos)

    def set_block_state(
        self, pos: BlockPos, state_id: int, *, source: object | None = None
    ) -> bool:
        """Apply a block update only when this bot references the chunk."""
        if pos.chunk not in self._held:
            return False
        return super().set_block_state(pos, state_id, source=source)

    def apply_multi_block_change(
        self, chunk_pos: ChunkPos, changes: Sequence[tuple[int, int, int, int]]
    ) -> list[tuple[BlockPos, int, int]]:
        """Apply a batch only when this bot references the chunk."""
        if chunk_pos not in self._held:
            return []
        return super().apply_multi_block_change(chunk_pos, changes)

    def find_blocks(
        self,
        matching: str | int | Callable[[int], bool],
        *,
        within: float = 32.0,
        around: Vec3 | BlockPos | None = None,
        count: int = 1,
    ) -> list[BlockPos]:
        """Find blocks only among the chunks this bot references."""
        held = {
            pos: column for pos, column in self._store.chunks.items() if pos in self._held
        }
        original = self.chunks
        self.chunks = held
        try:
            return super().find_blocks(matching, within=within, around=around, count=count)
        finally:
            self.chunks = original

    def snapshot(self, bounds: Bounds | None = None) -> WorldSnapshot:
        """Snapshot only the chunks this bot references."""
        chunks = {
            pos: column.copy()
            for pos, column in self._store.chunks.items()
            if pos in self._held and (bounds is None or bounds.contains_chunk(pos))
        }
        return WorldSnapshot(self.mc, chunks, min_y=self.min_y, height=self.height)

    @property
    def referenced_chunks(self) -> Mapping[ChunkPos, ChunkColumn]:
        """Read-only mapping of the chunks this bot references."""

        class _View(Mapping[ChunkPos, ChunkColumn]):
            def __init__(self, world: SharedWorld) -> None:
                self._world = world

            def __getitem__(self, pos: ChunkPos) -> ChunkColumn:
                if pos not in self._world._held:
                    raise KeyError(pos)
                return self._world._store.chunks[pos]

            def __iter__(self) -> Iterator[ChunkPos]:
                return iter(self._world._held)

            def __len__(self) -> int:
                return len(self._world._held)

        return _View(self)

    def __len__(self) -> int:
        return len(self._held)

    def __repr__(self) -> str:
        return (
            f"SharedWorld(bot={self._bot_id}, dimension={self.dimension!r}, "
            f"held={len(self._held)}, shared={len(self._store)})"
        )


class SharedWorldRegistry:
    """Owns one :class:`ChunkStore` per ``(server, dimension)``.

    Args:
        mc: Minecraft data used to build views.
        server: Stable server key, normally ``f"{host}:{port}"``.
    """

    __slots__ = ("_stores", "_views", "mc", "server")

    def __init__(self, mc: McData, *, server: str) -> None:
        self.mc = mc
        self.server = server
        self._stores: dict[WorldKey, ChunkStore] = {}
        self._views: dict[WorldKey, set[SharedWorld]] = {}

    def store(self, dimension: int | str = 0) -> ChunkStore:
        """Store for one dimension, created on first use."""
        key = WorldKey(self.server, dimension)
        store = self._stores.get(key)
        if store is None:
            store = ChunkStore(key)
            self._stores[key] = store
        return store

    def view(self, bot_id: int, dimension: int | str = 0) -> SharedWorld:
        """Create a per-bot view bound to ``dimension``."""
        view = SharedWorld(
            self.mc,
            self,
            server=self.server,
            dimension=dimension,
            bot_id=bot_id,
        )
        self._views.setdefault(WorldKey(self.server, dimension), set()).add(view)
        return view

    def release(self, view: SharedWorld) -> None:
        """Release every ref held by ``view`` and forget it."""
        view.clear()
        for views in self._views.values():
            views.discard(view)

    def clear(self) -> None:
        """Release every view (cluster shutdown)."""
        for view in [view for views in self._views.values() for view in views]:
            view.clear()
        self._views.clear()
        self._stores.clear()

    def stats(self) -> dict[str, int]:
        """Chunk/ref/memory counters across every dimension."""
        totals = {"worlds": len(self._stores), "chunks": 0, "refs": 0, "sections": 0, "bytes": 0}
        for store in self._stores.values():
            stats = store.stats()
            totals["chunks"] += stats["chunks"]
            totals["refs"] += stats["refs"]
            totals["sections"] += stats["sections"]
            totals["bytes"] += stats["estimated_bytes"]
        return totals

    def __len__(self) -> int:
        return sum(len(store) for store in self._stores.values())

    def __repr__(self) -> str:
        return f"SharedWorldRegistry(server={self.server!r}, stores={len(self._stores)})"
