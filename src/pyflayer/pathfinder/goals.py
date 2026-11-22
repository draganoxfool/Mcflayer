"""Pathfinding goals.

A goal answers two questions: ``is_end(pos)`` (has the search arrived?) and ``heuristic(pos)`` (an
admissible estimate of the remaining cost). Goals are immutable values.

Examples:
    >>> goal = GoalNear(BlockPos(10, 64, 10), 2)
    >>> goal.is_end(BlockPos(14, 64, 10))
    False
    >>> goal.is_end(BlockPos(12, 64, 10))
    True
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pyflayer.models.vec3 import BlockPos

__all__ = [
    "Goal",
    "GoalBlock",
    "GoalCompositeAll",
    "GoalCompositeAny",
    "GoalFollow",
    "GoalGetToBlock",
    "GoalInvert",
    "GoalLookAt",
    "GoalNear",
    "GoalXZ",
    "GoalY",
]


@runtime_checkable
class Goal(Protocol):
    """Search target."""

    def is_end(self, pos: BlockPos) -> bool:
        """True when ``pos`` satisfies the goal."""
        ...

    def heuristic(self, pos: BlockPos) -> float:
        """Admissible remaining-cost estimate from ``pos``."""
        ...


def _distance(a: BlockPos, b: BlockPos) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


@dataclass(frozen=True, slots=True)
class GoalBlock:
    """Stand exactly on ``pos``."""

    pos: BlockPos

    def is_end(self, pos: BlockPos) -> bool:
        return pos == self.pos

    def heuristic(self, pos: BlockPos) -> float:
        return _distance(pos, self.pos)


@dataclass(frozen=True, slots=True)
class GoalNear:
    """Be within ``radius`` blocks (Euclidean) of ``pos``."""

    pos: BlockPos
    radius: float = 1.0

    def is_end(self, pos: BlockPos) -> bool:
        return _distance(pos, self.pos) <= self.radius

    def heuristic(self, pos: BlockPos) -> float:
        return max(0.0, _distance(pos, self.pos) - self.radius)


@dataclass(frozen=True, slots=True)
class GoalXZ:
    """Reach an X/Z column within ``radius`` blocks, ignoring Y."""

    x: int
    z: int
    radius: float = 1.0

    def is_end(self, pos: BlockPos) -> bool:
        dx = pos.x - self.x
        dz = pos.z - self.z
        return math.hypot(dx, dz) <= self.radius

    def heuristic(self, pos: BlockPos) -> float:
        return max(0.0, math.hypot(pos.x - self.x, pos.z - self.z) - self.radius)


@dataclass(frozen=True, slots=True)
class GoalY:
    """Reach a Y level (any X/Z)."""

    y: int

    def is_end(self, pos: BlockPos) -> bool:
        return pos.y == self.y

    def heuristic(self, pos: BlockPos) -> float:
        return float(abs(pos.y - self.y))


@dataclass(frozen=True, slots=True)
class GoalGetToBlock:
    """Reach the block or stand next to it (including above/below)."""

    pos: BlockPos

    def is_end(self, pos: BlockPos) -> bool:
        return abs(pos.x - self.pos.x) + abs(pos.y - self.pos.y) + abs(
            pos.z - self.pos.z
        ) <= 1

    def heuristic(self, pos: BlockPos) -> float:
        return max(0.0, _distance(pos, self.pos) - 1.0)


@dataclass(frozen=True, slots=True)
class GoalFollow:
    """Stay within ``distance`` of a (possibly moving) target.

    ``target`` may be a ``BlockPos`` or a callable returning one; a callable lets the executor
    re-target per tick without rebuilding the goal.
    """

    target: BlockPos | Callable[[], BlockPos]
    distance: float = 2.0

    def _target(self) -> BlockPos:
        return self.target() if callable(self.target) else self.target

    def is_end(self, pos: BlockPos) -> bool:
        return _distance(pos, self._target()) <= self.distance

    def heuristic(self, pos: BlockPos) -> float:
        return max(0.0, _distance(pos, self._target()) - self.distance)


@dataclass(frozen=True, slots=True)
class GoalCompositeAny:
    """Satisfied by any child goal."""

    goals: tuple[Goal, ...]

    def __init__(self, goals: Iterable[Goal]) -> None:
        object.__setattr__(self, "goals", tuple(goals))

    def is_end(self, pos: BlockPos) -> bool:
        return any(goal.is_end(pos) for goal in self.goals)

    def heuristic(self, pos: BlockPos) -> float:
        return min((goal.heuristic(pos) for goal in self.goals), default=0.0)


@dataclass(frozen=True, slots=True)
class GoalCompositeAll:
    """Satisfied only when every child goal is satisfied."""

    goals: tuple[Goal, ...]

    def __init__(self, goals: Iterable[Goal]) -> None:
        object.__setattr__(self, "goals", tuple(goals))

    def is_end(self, pos: BlockPos) -> bool:
        return all(goal.is_end(pos) for goal in self.goals)

    def heuristic(self, pos: BlockPos) -> float:
        return max((goal.heuristic(pos) for goal in self.goals), default=0.0)


@dataclass(frozen=True, slots=True)
class GoalInvert:
    """Satisfied when the child goal is not."""

    goal: Goal

    def is_end(self, pos: BlockPos) -> bool:
        return not self.goal.is_end(pos)

    def heuristic(self, pos: BlockPos) -> float:
        return 0.0


@dataclass(frozen=True, slots=True)
class GoalLookAt:
    """Get within ``distance`` of a block/entity position.

    Orientation is the executor's job; the pathfinder only closes the distance.
    """

    pos: BlockPos
    distance: float = 3.0

    def is_end(self, pos: BlockPos) -> bool:
        return _distance(pos, self.pos) <= self.distance

    def heuristic(self, pos: BlockPos) -> float:
        return max(0.0, _distance(pos, self.pos) - self.distance)
