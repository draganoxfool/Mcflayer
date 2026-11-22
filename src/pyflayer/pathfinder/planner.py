"""Planning entry point: snapshot, search off-loop, cache.

`PathPlanner.plan` never burns the event loop: it takes a cheap ``WorldSnapshot`` and runs A* in a
worker thread through :func:`~pyflayer._internal.cpu.run_cpu`. `plan_sync` is available for tests
and for callers that already own a worker thread.

Examples:
    >>> planner = PathPlanner(world, mc)
    >>> path = await planner.plan(BlockPos(0, 64, 0), GoalBlock(BlockPos(8, 64, 0)))
    >>> path.complete
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pyflayer._internal.cpu import run_cpu
from pyflayer.data.loader import McData
from pyflayer.errors import NoPath
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.pathfinder.astar import PathSearchResult, search
from pyflayer.pathfinder.goals import Goal
from pyflayer.world.store import WorldKey
from pyflayer.world.view import WorldSnapshot

__all__ = ["Path", "PathPlanner", "SnapshotWorld"]


class SnapshotWorld(Protocol):
    """A mutable world that can produce an immutable snapshot."""

    def snapshot(self) -> WorldSnapshot: ...


class PathCacheLike(Protocol):
    """Cache surface accepted by the planner (``swarm.PathCache`` satisfies it)."""

    def make_key(
        self,
        world: WorldKey,
        start: BlockPos | Vec3,
        goal: object,
        *,
        version: int = 0,
    ) -> object: ...

    def get(self, key: object) -> object | None: ...

    def put(self, key: object, value: object) -> None: ...


@dataclass(frozen=True, slots=True)
class Path:
    """A planned route of block positions (feet blocks), including the start."""

    points: tuple[BlockPos, ...]
    complete: bool
    cost: float = 0.0
    expanded: int = 0

    @property
    def end(self) -> BlockPos | None:
        """Last waypoint, or ``None`` for an empty path."""
        return self.points[-1] if self.points else None

    def __len__(self) -> int:
        return len(self.points)


class PathPlanner:
    """Builds paths and optionally caches them.

    Args:
        world: Live world or an existing snapshot.
        mc: Data used to classify block states.
        max_nodes: A* node budget per search.
        max_drop: Maximum controlled fall, in blocks.
        cache: Optional shared path cache.
        world_key: Cache namespace (``(server, dimension)``).
    """

    __slots__ = ("cache", "max_drop", "max_nodes", "mc", "world", "world_key")

    def __init__(
        self,
        world: SnapshotWorld,
        mc: McData,
        *,
        max_nodes: int = 5000,
        max_drop: int = 3,
        cache: PathCacheLike | None = None,
        world_key: WorldKey | None = None,
    ) -> None:
        self.world = world
        self.mc = mc
        self.max_nodes = max_nodes
        self.max_drop = max_drop
        self.cache = cache
        self.world_key = world_key

    def plan_sync(
        self,
        start: BlockPos | Vec3,
        goal: Goal,
        *,
        allow_partial: bool = False,
    ) -> Path:
        """Plan on the calling thread and return a :class:`Path`."""
        start_pos = start.floored() if isinstance(start, Vec3) else start
        cached = self._cached(start_pos, goal)
        if cached is not None:
            return cached
        result, snapshot = self._search(self.world, start_pos, goal)
        path = self._to_path(result)
        if not result.complete and not allow_partial:
            raise NoPath("no path to goal", partial=path)
        self._store(start_pos, goal, path)
        del snapshot
        return path

    async def plan(
        self,
        start: BlockPos | Vec3,
        goal: Goal,
        *,
        allow_partial: bool = False,
    ) -> Path:
        """Plan off the event loop against a snapshot."""
        start_pos = start.floored() if isinstance(start, Vec3) else start
        cached = self._cached(start_pos, goal)
        if cached is not None:
            return cached
        snapshot = self._snapshot(self.world)
        result = await run_cpu(
            search,
            snapshot,
            self.mc,
            start_pos,
            goal,
            max_nodes=self.max_nodes,
            max_drop=self.max_drop,
            budget_ms=10.0,
        )
        path = self._to_path(result)
        if not result.complete and not allow_partial:
            raise NoPath("no path to goal", partial=path)
        self._store(start_pos, goal, path)
        return path

    def _snapshot(self, world: SnapshotWorld) -> WorldSnapshot:
        if isinstance(world, WorldSnapshot):
            return world
        return world.snapshot()

    def _search(
        self, world: SnapshotWorld, start: BlockPos, goal: Goal
    ) -> tuple[PathSearchResult, WorldSnapshot]:
        snapshot = self._snapshot(world)
        return (
            search(
                snapshot,
                self.mc,
                start,
                goal,
                max_nodes=self.max_nodes,
                max_drop=self.max_drop,
            ),
            snapshot,
        )

    @staticmethod
    def _to_path(result: PathSearchResult) -> Path:
        return Path(result.path, result.complete, result.cost, result.expanded)

    def _cache_key(self, start: BlockPos, goal: Goal) -> object | None:
        if self.cache is None or self.world_key is None:
            return None
        if callable(getattr(goal, "target", None)):
            return None  # moving targets cannot be cached
        return self.cache.make_key(self.world_key, start, repr(goal))

    def _cached(self, start: BlockPos, goal: Goal) -> Path | None:
        key = self._cache_key(start, goal)
        if key is None or self.cache is None:
            return None
        value = self.cache.get(key)
        return value if isinstance(value, Path) else None

    def _store(self, start: BlockPos, goal: Goal, path: Path) -> None:
        key = self._cache_key(start, goal)
        if key is not None and self.cache is not None:
            self.cache.put(key, path)
