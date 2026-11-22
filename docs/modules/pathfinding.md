# Pathfinding (`pyflayer.pathfinder`)

`pyflayer.pathfinder` provides A* search over block nodes and a per-tick executor. `search()` reads a
world view synchronously; `PathPlanner.plan()` snapshots the world and runs the search in a worker
thread through `run_cpu`. The returned path can be followed by `PathExecutor` through an action
lease.

```python
from pyflayer.pathfinder import GoalBlock, PathPlanner
from pyflayer.models import BlockPos

planner = PathPlanner(bot.world, bot.world.mc)
path = await planner.plan(bot.position, GoalBlock(BlockPos(20, 64, 20)))
print(path.end, path.complete, path.cost, path.expanded)
```

The normal front door is `bot.actions.goto(...)`, which already combines planning, following and the
scheduler; use the classes directly for custom goals, caching or tests.

## Goals

A goal is any object with `is_end(pos: BlockPos) -> bool` and `heuristic(pos) -> float`. All bundled
goals are immutable dataclasses in `pyflayer.pathfinder.goals`.

| Goal | Satisfied when |
|---|---|
| `GoalBlock(pos)` | The feet block is exactly `pos` |
| `GoalNear(pos, radius=1.0)` | Within `radius` blocks (Euclidean) of `pos` |
| `GoalXZ(x, z, radius=1.0)` | The X/Z column is within `radius`, ignoring Y |
| `GoalY(y)` | The feet block is at height `y` |
| `GoalGetToBlock(pos)` | Standing on, above or next to `pos` (Manhattan distance ≤ 1) |
| `GoalFollow(target, distance=2.0)` | Within `distance` of a `BlockPos` or a callable returning one |
| `GoalCompositeAny(goals)` | Any child goal is satisfied |
| `GoalCompositeAll(goals)` | Every child goal is satisfied |
| `GoalInvert(goal)` | The child goal is **not** satisfied (heuristic `0`) |
| `GoalLookAt(pos, distance=3.0)` | Within `distance`; facing is the executor's job |

`GoalFollow` accepts a callable so moving targets can be re-read without rebuilding the goal.
`GoalNear`, `GoalXZ` and the composites subtract the radius from their heuristic, keeping it
admissible.

## A* search

### `search(world, mc, start, goal, *, max_nodes=5000, max_drop=3) -> PathSearchResult`

Runs one bounded search from the player's feet block.

| Parameter | Meaning |
|---|---|
| `world` | Object with `min_y`, `height`, `block_state_id(pos)` and `is_loaded(chunk)`; a `WorldSnapshot` qualifies |
| `mc` | `McData` used to classify block states |
| `start` | Starting feet block |
| `goal` | Goal predicate and heuristic |
| `max_nodes` | Node expansion budget; the best partial path is returned when exhausted |
| `max_drop` | Maximum controlled fall, in blocks |

`PathSearchResult` contains `path` (a tuple of `BlockPos`, including the start), `complete`, `cost`
and `expanded`. `result.end` is the last node or `None` for an empty path.

Search costs are expressed in physics ticks:

| Move | Cost |
|---|---:|
| Flat walk | `4.633` |
| Diagonal walk | `6.550` |
| Jump/step up one block | `8.633` |
| Climb a ladder/vine one block | `4.633` |
| Controlled fall | `2.0 + 1.5 × blocks` |

Moves are generated conservatively:

- the feet and head cells must be clear, and the feet must rest on a solid, non-hazard support;
- diagonal moves require **both** adjacent side cells to be clear (no corner cutting);
- jumps require headroom above the start and landing cells;
- falls stop at the first unsafe or blocked cell and are limited to `max_drop`;
- ladders, vines and scaffolding climb vertically without ground support;
- unknown block states and unloaded chunks are never traversable;
- lava, fire, cactus, magma, sweet berry bushes and powder snow are hazards.

`BlockClassifier` caches collision/hazard/climbable flags per state id, so repeated queries in one
search are cheap. The heap is ordered by `(f, h, insertion sequence)`, which makes ties deterministic.

## Planning off the event loop

### `class PathPlanner`

```python
PathPlanner(world, mc, *, max_nodes=5000, max_drop=3, cache=None, world_key=None)
```

| Member | Meaning |
|---|---|
| `plan_sync(start, goal, *, allow_partial=False)` | Plan on the calling thread (tests/tools) |
| `await plan(start, goal, *, allow_partial=False)` | Snapshot, then search via `run_cpu` |
| `max_nodes` / `max_drop` | Per-search limits |

Both methods accept a `BlockPos` or a `Vec3` (floored). If the goal cannot be reached they raise
`NoPath` with the best partial `Path` in `exc.fields["partial"]`, unless `allow_partial=True`. A
complete path is returned either way.

The optional `cache` is any object with `make_key`, `get` and `put` — `swarm.PathCache` satisfies it.
The optional `cache` is any object with `make_key`, `get` and `put`; `swarm.PathCache` satisfies
that interface. Pass a `WorldKey` as `world_key` to enable caching. `GoalFollow` with a callable
target is not cached. The planner currently uses the cache key's default world version and does not
automatically invalidate paths after block changes; callers must invalidate or replace affected
entries.

### `class Path`

A frozen path value:

| Member | Meaning |
|---|---|
| `points` | Tuple of `BlockPos`, including the start |
| `complete` | False for a partial path |
| `cost` | Accumulated physics-tick cost |
| `expanded` | Nodes expanded by the search |
| `end` | Last point, or `None` |
| `len(path)` | Number of waypoints |

## Following a path

### `class PathExecutor`

```python
PathExecutor(host, *, reach=0.28, stuck_ticks=60, max_ticks_per_node=240)
```

`await executor.follow(path, lease)` walks every waypoint after the first. Each tick it:

1. checks whether the feet are within `reach` horizontally and a small vertical band of the waypoint;
2. looks along the horizontal vector, sets forward input and sprints when more than 3 blocks away;
3. jumps when the next node is higher by more than `0.2`;
4. awaits the next `PhysicsTickEvent` (1 s timeout).

It fails with `ActionFailed` after `stuck_ticks` consecutive ticks with less than `0.005` blocks of
movement, or after `max_ticks_per_node`. On completion or failure it zeroes movement through the
lease. The executor writes **only** through the lease, so a survival action can preempt it; `GoTo`
is `RESUME`, so the route is replanned from the checkpoint.

## Execution policy

`GoTo` uses these defaults:

| Setting | Value |
|---|---|
| Resources | `MOVEMENT | LOOK` |
| Preemption | `RESUME` (checkpoint is the goal) |
| Priority | `WORK` through `bot.actions.goto` |
| `max_nodes` | `5000` |
| `allow_partial` | `False` |

Planning happens before movement starts, so an unreachable goal raises `NoPath` without moving the
bot. `PathExecutor` then dispatches `PathStartedEvent` once, `PathUpdatedEvent` per waypoint,
`PathResetEvent` on failure and `GoalReachedEvent` on completion.

```python
from pyflayer import BlockPos, GoalBlock
from pyflayer.actions import Priority

await bot.actions.goto(GoalBlock(BlockPos(40, 64, -8)), priority=Priority.WORK)
```

## Limitations

- The search is 3-D but movement is walking/jumping/falling/climbing; swimming, boats, horses,
  parkour jumps and 1-block ceilings are not modelled.
- `max_nodes` is a hard expansion budget, not a time limit. `run_cpu` logs if the configured 10 ms
  soft budget is exceeded; this is a warning threshold, not a cancellation deadline.
- A partial path is returned on budget exhaustion; callers must opt into following it.
- The planner does not re-plan when the world changes mid-path. `PathExecutor` fails and `GoTo`
  resumes only after a preemption; live block changes are the caller's responsibility.
- `GoalInvert` has no useful heuristic and can expand the whole budget.
- No jump physics lookahead: a path may require a jump that the executor requests one tick at a
  time.
