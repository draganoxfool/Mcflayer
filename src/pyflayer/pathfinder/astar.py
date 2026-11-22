"""Deterministic A* over block nodes.

The search runs on an immutable world view (normally a ``WorldSnapshot``) and is pure: the same
input produces the same path. Costs are expressed in physics ticks so ``GoTo`` can compare routes
with the executor's expectations. When the node budget runs out the best partial path is returned.

Examples:
    >>> from pyflayer.pathfinder import GoalBlock, search
    >>> result = search(world, mc, BlockPos(0, 64, 0), GoalBlock(BlockPos(4, 64, 0)))
    >>> result.complete
    True
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from pyflayer.data.loader import McData
from pyflayer.models.vec3 import BlockPos, ChunkPos
from pyflayer.pathfinder.goals import Goal

__all__ = [
    "COST_ASCEND",
    "COST_CLIMB",
    "COST_DIAGONAL",
    "COST_TRAVERSE",
    "BlockClassifier",
    "PathSearchResult",
    "WorldView",
    "search",
]

COST_TRAVERSE = 4.633
COST_DIAGONAL = 6.550
COST_ASCEND = 8.633
COST_CLIMB = 4.633
COST_FALL_BASE = 2.0
COST_FALL_PER_BLOCK = 1.5

#: Blocks that make a landing unsafe regardless of their collision box.
_HAZARDS = frozenset(
    {
        "lava",
        "flowing_lava",
        "fire",
        "cactus",
        "magma",
        "magma_block",
        "sweet_berry_bush",
        "powder_snow",
    }
)
_CLIMBABLE = frozenset({"ladder", "vine", "scaffolding"})


class WorldView(Protocol):
    """Minimal world surface used by the planner."""

    min_y: int
    height: int

    def block_state_id(self, pos: BlockPos) -> int: ...

    def is_loaded(self, pos: ChunkPos) -> bool: ...


@dataclass(frozen=True, slots=True)
class PathSearchResult:
    """Outcome of one A* search."""

    path: tuple[BlockPos, ...]
    complete: bool
    cost: float
    expanded: int

    @property
    def end(self) -> BlockPos | None:
        """Last node of the path."""
        return self.path[-1] if self.path else None


@dataclass(frozen=True, slots=True)
class _Flags:
    solid: bool
    hazard: bool
    climbable: bool


class BlockClassifier:
    """Caches collision/hazard/climbable flags per block-state id."""

    __slots__ = ("_cache", "mc")

    def __init__(self, mc: McData) -> None:
        self.mc = mc
        self._cache: dict[int, _Flags] = {}

    def flags(self, state_id: int) -> _Flags:
        cached = self._cache.get(state_id)
        if cached is not None:
            return cached
        try:
            block, _metadata = self.mc.blocks.from_state_id(state_id)
        except Exception:
            cached = _Flags(True, True, False)  # unknown states are never traversable
            self._cache[state_id] = cached
            return cached
        try:
            solid = bool(self.mc.collision_boxes(state_id))
        except Exception:
            solid = True
        name = block.name
        cached = _Flags(
            solid=solid,
            hazard=name in _HAZARDS,
            climbable=name in _CLIMBABLE,
        )
        self._cache[state_id] = cached
        return cached


@dataclass(slots=True)
class _Node:
    pos: BlockPos
    g: float
    h: float
    parent: _Node | None

    @property
    def f(self) -> float:
        return self.g + self.h


def search(
    world: WorldView,
    mc: McData,
    start: BlockPos,
    goal: Goal,
    *,
    max_nodes: int = 5000,
    max_drop: int = 3,
) -> PathSearchResult:
    """Run A* from ``start`` to ``goal``.

    Args:
        world: Immutable world view (snapshot recommended).
        mc: Data used to classify block states.
        start: Starting block (the player's feet block).
        goal: Goal predicate and heuristic.
        max_nodes: Search budget; the best partial path is returned on exhaustion.
        max_drop: Maximum controlled fall, in blocks.
    """
    if max_nodes < 1:
        raise ValueError("max_nodes must be at least 1")
    classifier = BlockClassifier(mc)
    cache = _MoveCache(world, mc, classifier, max_drop=max_drop)

    root = _Node(start, 0.0, float(goal.heuristic(start)), None)
    if goal.is_end(start):
        return PathSearchResult((start,), True, 0.0, 0)

    counter = itertools.count()
    open_heap: list[tuple[float, float, int, _Node]] = [(root.f, root.h, next(counter), root)]
    best_scores: dict[BlockPos, float] = {start: 0.0}
    best_partial = root
    expanded = 0

    while open_heap and expanded < max_nodes:
        _f, _h, _seq, node = heapq.heappop(open_heap)
        if node.g > best_scores.get(node.pos, float("inf")):
            continue
        expanded += 1
        if node.h < best_partial.h:
            best_partial = node
        if goal.is_end(node.pos):
            return PathSearchResult(_reconstruct(node), True, node.g, expanded)

        for neighbor, cost in cache.moves(node.pos):
            tentative = node.g + cost
            if tentative >= best_scores.get(neighbor, float("inf")):
                continue
            best_scores[neighbor] = tentative
            child = _Node(neighbor, tentative, float(goal.heuristic(neighbor)), node)
            heapq.heappush(open_heap, (child.f, child.h, next(counter), child))

    return PathSearchResult(_reconstruct(best_partial), False, best_partial.g, expanded)


def _reconstruct(node: _Node) -> tuple[BlockPos, ...]:
    points: list[BlockPos] = []
    current: _Node | None = node
    while current is not None:
        points.append(current.pos)
        current = current.parent
    points.reverse()
    return tuple(points)


class _MoveCache:
    """Per-search move generation and block classification."""

    __slots__ = ("_classifier", "_world", "max_drop")

    def __init__(
        self,
        world: WorldView,
        mc: McData,
        classifier: BlockClassifier,
        *,
        max_drop: int,
    ) -> None:
        self._world = world
        self._classifier = classifier
        self.max_drop = max_drop

    def _state(self, pos: BlockPos) -> int | None:
        if not (self._world.min_y <= pos.y < self._world.min_y + self._world.height):
            return None
        if not self._world.is_loaded(pos.chunk):
            return None
        try:
            return self._world.block_state_id(pos)
        except Exception:
            return None

    def _flags(self, pos: BlockPos) -> _Flags | None:
        state = self._state(pos)
        if state is None:
            return None
        return self._classifier.flags(state)

    def clear(self, pos: BlockPos) -> bool:
        flags = self._flags(pos)
        return flags is not None and not flags.solid and not flags.hazard

    def standable(self, pos: BlockPos) -> bool:
        feet = self._flags(pos)
        head = self._flags(BlockPos(pos.x, pos.y + 1, pos.z))
        support = self._flags(BlockPos(pos.x, pos.y - 1, pos.z))
        if feet is None or head is None or support is None:
            return False
        return (
            not feet.solid
            and not feet.hazard
            and not head.solid
            and not head.hazard
            and support.solid
            and not support.hazard
        )

    def moves(self, pos: BlockPos) -> Iterator[tuple[BlockPos, float]]:
        """Yield ``(neighbor, cost)`` for one node."""
        seen: set[BlockPos] = set()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            flat = BlockPos(pos.x + dx, pos.y, pos.z + dz)
            if not self._loaded(flat):
                continue
            if self.clear(flat) and self.clear(BlockPos(flat.x, flat.y + 1, flat.z)):
                if self.standable(flat):
                    yield flat, COST_TRAVERSE
                    seen.add(flat)
                # Jump up one block (stairs, a single-block step).
                up = BlockPos(flat.x, flat.y + 1, flat.z)
                if (
                    self.standable(up)
                    and self.clear(BlockPos(pos.x, pos.y + 2, pos.z))
                    and self.clear(BlockPos(flat.x, flat.y + 2, flat.z))
                ):
                    yield up, COST_ASCEND
                    seen.add(up)
                # Controlled fall into a safe landing.
                for drop in range(1, self.max_drop + 1):
                    below = BlockPos(flat.x, flat.y - drop, flat.z)
                    if not self.clear(below) or not self.clear(
                        BlockPos(below.x, below.y + 1, below.z)
                    ):
                        break
                    if self.standable(below):
                        yield below, COST_FALL_BASE + COST_FALL_PER_BLOCK * drop
                        seen.add(below)
                        break
            # Ladders/vines climb vertically without ground support.
            flags = self._flags(flat)
            if flags is not None and flags.climbable:
                up = BlockPos(flat.x, flat.y + 1, flat.z)
                if self.clear(up) and self.clear(BlockPos(up.x, up.y + 1, up.z)):
                    yield up, COST_CLIMB
                    seen.add(up)
        for dx, dz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            diagonal = BlockPos(pos.x + dx, pos.y, pos.z + dz)
            if diagonal in seen or not self._loaded(diagonal):
                continue
            side_a = BlockPos(pos.x + dx, pos.y, pos.z)
            side_b = BlockPos(pos.x, pos.y, pos.z + dz)
            if not (
                self.clear(side_a)
                and self.clear(side_b)
                and self.clear(diagonal)
                and self.standable(diagonal)
            ):
                continue
            yield diagonal, COST_DIAGONAL

    def _loaded(self, pos: BlockPos) -> bool:
        return (
            self._world.min_y <= pos.y < self._world.min_y + self._world.height
            and bool(self._world.is_loaded(pos.chunk))
        )
