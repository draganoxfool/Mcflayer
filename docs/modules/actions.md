# Actions (`pyflayer.actions`)

`Bot` owns an `ActionScheduler` and exposes an `ActionFacade` as `bot.actions`. The scheduler
arbitrates resources for submitted actions and grants a lease while each action runs. Direct calls
to bot methods remain possible and are outside scheduler arbitration.

The action layer is the **only writer** of movement, look, hand and window controls. Every built-in
behaviour (walking, digging, eating, attacking) runs as an action under
[`ActionScheduler`](#class-actionscheduler), which arbitrates capabilities all-or-nothing and lets
urgent work preempt long-running jobs without leaving the bot mid-swing.

```python
from pyflayer.actions import Priority
from pyflayer.models import BlockPos

handle = bot.actions.goto(BlockPos(12, 64, -4), priority=Priority.WORK)
await handle
await bot.actions.dig(BlockPos(12, 63, -4))
```

[[toc]]

## Resources and priorities

Actions declare the resources they need; the scheduler acquires **all** of them or none, so two
actions can never deadlock by holding different halves of a set.

| Resource | Held by |
|---|---|
| `MOVEMENT` | `GoTo`, custom walking actions |
| `LOOK` | `Look`, `LookAt`, `Dig`, `Place`, `Attack`, `GoTo` |
| `HANDS` | `Dig`, `Place`, `Attack`, `Eat` |
| `WINDOW` | `Equip`, `Eat` |
| `CHAT` | reserved for chat actions |

`Priority` is an `IntEnum` ordered from low to high:

| Priority | Value | Typical use |
|---|---:|---|
| `IDLE` | 0 | Background movement that may always yield |
| `BACKGROUND` | 10 | Maintenance, low-value scouting |
| `WORK` | 20 | The default: mining, building, `goto` |
| `USER` | 30 | Explicit user commands |
| `COMBAT` | 60 | Fighting (used by `bot.actions.attack`) |
| `SURVIVAL` | 90 | Eating and emergency escape |
| `EMERGENCY` | 100 | Death barrier / hard stop path |

A holder at a lower priority is **preempted cooperatively**: its task is cancelled, it gets one
`on_preempted()` call (at most 150 ms by default), its checkpoint is taken if it is resumable, its
controls are zeroed and the lease is revoked. The old holder sees `ActionPreempted`; the preemptor
then acquires the resources. `lease.critical()` defers preemption while a multi-packet operation
(equip clicks, start/stop digging) is in flight.

Three policies are available through `OnPreempt`:

- `ABORT` (default) — surface `ActionPreempted`; the action is not retried.
- `RESUME` — save `checkpoint()`, then `restore()` and rerun under the new lease. `GoTo` uses this,
  so a survival eat does not throw away the route.
- `REQUEUE` — keep the handle pending and start again from scratch.

New actions can be rejected with `ActionBusy` (the default when no preemption is possible) or wait
with `queue=True`. A queued action never preempts the current holder.

## Scheduler

### `class ActionScheduler`

```python
scheduler = ActionScheduler(bot, clock=bot.clock)
handle = scheduler.run(Dig(pos), priority=Priority.WORK)
await handle
```

`Bot` creates one scheduler (`bot.scheduler`) and one facade (`bot.actions`). Every
`pyflayer.Bot` movement/look/hand control is coordinated through it.

| Member | Meaning |
|---|---|
| `run(action, *, priority=WORK, preempt=True, queue=False, timeout=None)` | Submit an action and return its `ActionHandle` immediately |
| `current(resource=None)` | Current holder, optionally for one resource |
| `active` / `idle` | Handles still pending/running; `idle` is true when none are |
| `cancel_all(reason="", below=EMERGENCY)` | Cancel everything below a priority |
| `set_barrier(True)` / `release_barrier()` | Death barrier: cancel current work and block new starts |
| `metrics()` | Diagnostic snapshot (holders, waiters, barrier) |

`run()` never awaits arbitration; the returned handle is the awaitable result. Timeouts are measured
on the injected `Clock`, so `FakeClock` makes them deterministic. A timed-out action fails with
`ActionFailed`, while a caller cancellation raises `ActionCancelled`.

### `class ActionHandle`

An `Awaitable[R]` with `action`, `priority`, `resources`, `state`, `done`, `cancelled`, `lease`,
`task`, `cancel(reason)`, `wait()` and `checkpoint`. The same handle can be awaited from several
places; the first result is shared.

### `class Lease`

The capability token passed to `Action.run`. Its `controls` is a write-only
`set_movement`/`look`/`jump` surface. Writing after revocation raises `LeaseRevoked`. `lease.child()`
runs a sub-action under the same resources (used by composite actions) without re-acquiring them.

## Built-in actions

Actions live in `pyflayer.actions.basic` and are re-exported from `pyflayer.actions`.

| Action | Result | Resources | Notes |
|---|---|---|---|
| `Look(yaw, pitch=0)` | `None` | `LOOK` | Absolute look |
| `LookAt(target)` | `None` | `LOOK` | Block, `Vec3` or tracked `Entity` |
| `GoTo(goal, *, allow_partial=False, max_nodes=5000)` | `Path` | `MOVEMENT | LOOK` | Plans with `PathPlanner`, follows with `PathExecutor`; resumable |
| `Dig(pos, *, reach=4.5)` | `bool` | `HANDS | LOOK` | Faces the block, then `break_block`; mining delay in survival |
| `Place(pos, *, face=Face.UP)` | `bool` | `HANDS | LOOK` | Range-checked, then `place_block` |
| `Equip(item, *, hotbar=0)` | `int` | `WINDOW` | Selects a hotbar stack or moves one from the main inventory with two clicks |
| `Eat(*, ticks=32)` | `str | None` | `WINDOW | HANDS` | First hotbar food; `SURVIVAL` priority at the facade |
| `Attack(target=None, *, reach=3.5)` | `Entity` | `LOOK | HANDS` | Entity, id, or nearest within reach; `COMBAT` priority |

`bot.actions` is the idiomatic surface:

```python
bot.actions.run(action, priority=..., timeout=...)
bot.actions.look(90, 0)
bot.actions.look_at(entity)
bot.actions.goto(goal, allow_partial=True)
bot.actions.dig(pos)
bot.actions.place(pos)
bot.actions.equip("diamond_pickaxe")
bot.actions.eat()
bot.actions.attack()
bot.actions.stop()
```

All facade methods return an `ActionHandle` and accept the same `priority`, `preempt`, `queue` and
`timeout` keyword arguments as `run()`. `goto` additionally accepts `allow_partial` and `max_nodes`;
`equip` accepts `hotbar`; `attack` accepts `reach`.

## Survival monitor

`SurvivalMonitor` subscribes to `HealthEvent` and, when health is at or below `threshold` (default
`6.0`) and food is available, submits `Eat()` at `Priority.SURVIVAL`. It ignores deaths and duplicate
eats. The bot starts it on `JoinEvent` and stops it on close/disconnect; `bot.survival.enabled` can
disable the policy without unsubscribing.

```python
bot.survival.threshold = 8.0
bot.survival.enabled = False
```

## Events

The scheduler and executor emit:

| Event | Handler | Emitted when |
|---|---|---|
| `ActionStartedEvent(action, priority, resources)` | `on_action_started` | A lease was granted and `run()` started |
| `ActionFinishedEvent(action, state, duration, error=None)` | `on_action_finished` | Terminal state reached |
| `ActionPreemptedEvent(action, by=None)` | `on_action_preempted` | A higher-priority action took the lease |
| `PathStartedEvent(goal, complete, length)` | `on_path_started` | A plan is ready and following starts |
| `PathUpdatedEvent(position, waypoint)` | `on_path_updated` | A waypoint was reached |
| `PathResetEvent(reason)` | `on_path_reset` | The path was abandoned |
| `GoalReachedEvent(goal)` | `on_goal_reached` | The final waypoint was reached |

Events are informational; the scheduler never waits for listeners.

## Commands

`pyflayer.ext.commands.requires_idle()` gates a command while any action is running:

```python
from pyflayer.ext import commands


@commands.command()
@commands.requires_idle()
async def mine(ctx):
    await ctx.bot.actions.dig(BlockPos(8, 64, 8))
```

## Limitations

- The scheduler coordinates **cooperative** actions. Third-party code that writes `set_movement` or
  `look` directly bypasses leases and can fight an action.
- `WINDOW` operations are serialized, but inventory-click rollback on a failed click is not
  implemented; `Equip` assumes the server accepts both clicks.
- `Attack` sends one swing; no knockback, cooldown or reach prediction beyond a distance check.
- Eating waits a fixed number of ticks (32 by default) rather than watching the food level.
- The death barrier is released by `RespawnEvent`; a disconnect closes the bot and cancels actions.
