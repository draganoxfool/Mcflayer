"""A* pathfinding over immutable world snapshots.

Planning is synchronous and pure over a :class:`~pyflayer.world.view.WorldSnapshot`;
:class:`PathPlanner` takes the snapshot once and moves the search off the event loop with
:func:`~pyflayer._internal.cpu.run_cpu`. :class:`PathExecutor` turns a path into per-tick controls
through an action lease.

Examples:
    >>> path = planner.plan_sync(start, GoalBlock(BlockPos(8, 64, 8)))
    >>> len(path) > 0
    True
"""

from __future__ import annotations

from pyflayer.events.catalog import GoalReachedEvent
from pyflayer.pathfinder.astar import (
    BlockClassifier,
    PathSearchResult,
    WorldView,
    search,
)
from pyflayer.pathfinder.executor import PathExecutor
from pyflayer.pathfinder.goals import (
    Goal,
    GoalBlock,
    GoalCompositeAll,
    GoalCompositeAny,
    GoalFollow,
    GoalGetToBlock,
    GoalInvert,
    GoalLookAt,
    GoalNear,
    GoalXZ,
    GoalY,
)
from pyflayer.pathfinder.planner import Path, PathPlanner

__all__ = [
    "BlockClassifier",
    "Goal",
    "GoalBlock",
    "GoalCompositeAll",
    "GoalCompositeAny",
    "GoalFollow",
    "GoalGetToBlock",
    "GoalInvert",
    "GoalLookAt",
    "GoalNear",
    "GoalReachedEvent",
    "GoalXZ",
    "GoalY",
    "Path",
    "PathExecutor",
    "PathPlanner",
    "PathSearchResult",
    "WorldView",
    "search",
]
