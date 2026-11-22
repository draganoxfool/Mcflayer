# `pyflayer.pathfinder`

Deterministic A* over world snapshots and the per-tick path executor. This page documents the public
classes and functions; the [guide](../modules/pathfinding.md) explains move generation, costs and
execution.

```python
from pyflayer.pathfinder import GoalBlock, PathExecutor, PathPlanner, search
```

## Goals

::: pyflayer.pathfinder.goals.Goal

::: pyflayer.pathfinder.goals.GoalBlock

::: pyflayer.pathfinder.goals.GoalNear

::: pyflayer.pathfinder.goals.GoalXZ

::: pyflayer.pathfinder.goals.GoalY

::: pyflayer.pathfinder.goals.GoalGetToBlock

::: pyflayer.pathfinder.goals.GoalFollow

::: pyflayer.pathfinder.goals.GoalCompositeAny

::: pyflayer.pathfinder.goals.GoalCompositeAll

::: pyflayer.pathfinder.goals.GoalInvert

::: pyflayer.pathfinder.goals.GoalLookAt

## Search

::: pyflayer.pathfinder.astar.search

::: pyflayer.pathfinder.astar.PathSearchResult
    options:
      members: [path, complete, cost, expanded, end]

::: pyflayer.pathfinder.astar.BlockClassifier

::: pyflayer.pathfinder.astar.WorldView

## Planning

::: pyflayer.pathfinder.planner.PathPlanner
    options:
      members: [plan, plan_sync]

::: pyflayer.pathfinder.planner.Path
    options:
      members: [points, complete, cost, expanded, end]

## Execution

::: pyflayer.pathfinder.executor.PathExecutor
    options:
      members: [follow]
