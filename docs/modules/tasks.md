# Tasks (`pyflayer.ext.tasks`)

`tasks.loop` runs a coroutine repeatedly. Intervals can be wall-clock (`seconds`, `minutes`,
`hours`), or Minecraft-native via `ticks=`, which synchronises iterations to the bot's
`PhysicsTickEvent` counter instead of wall time.

## Quick start

```python
from pyflayer.ext import commands, tasks


class Monitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.report.start()

    @tasks.loop(seconds=30)
    async def report(self):
        await self.bot.chat(f"hp={self.bot.health}")

    @report.before_loop
    async def before_report(self):
        await self.bot.wait_until_ready()

    @report.after_loop
    async def after_report(self):
        print("loop stopped")
```

## Physics-tick alignment

```python
@tasks.loop(ticks=5)
async def sample(self):
    # runs once every five physics ticks (four times a second at 20 TPS)
    ...
```

`ticks=N` waits for N `PhysicsTickEvent`s between iterations, so the loop stays aligned with the
simulation even when wall-clock timing drifts. Without a bot (for example in a unit test) it falls
back to `N / 20` seconds on the injected clock.

## Lifecycle

| Method | Meaning |
|---|---|
| `start()` | Start; returns the backing `asyncio.Task` |
| `stop()` | Finish the current iteration and stop |
| `cancel()` | Cancel the task immediately |
| `restart()` | Cancel and start again |
| `change_interval(seconds=…, ticks=…)` | Update the interval in place |
| `is_running()` | True while the task is live |
| `failed()` | True after an unhandled error stopped the loop |
| `is_being_cancelled()` | True while cancellation is in progress |
| `current_loop` | Completed iterations |

## Hooks

- `@loop.before_loop` — awaited once before the first iteration. Conventionally awaits
  `bot.wait_until_ready()`.
- `@loop.after_loop` — awaited after the loop stops normally.
- `@loop.error` — receives `(loop, exception)`; without it, an exception stops the loop and logs.

## Options

```python
@tasks.loop(seconds=10, count=3, reconnect=True, name="heartbeat")
async def heartbeat(self): ...
```

| Option | Meaning |
|---|---|
| `seconds` / `minutes` / `hours` | Wall-clock interval; at most one |
| `ticks` | Physics-tick interval (Minecraft-native) |
| `count` | Stop after this many iterations; `None` runs forever |
| `reconnect` | Reserved for pause/resume across reconnects |
| `name` | Log/task name |

## Cogs and reloads

Loops are descriptors. Declared in a `Cog`, they bind to the cog instance and use `cog.bot` for the
clock and readiness. `add_cog` resumes loops that were started; `remove_cog` cancels them, so an
extension reload never leaks a loop task.

Standalone loops (declared outside a cog) are also supported; call `start()` where an event loop is
running.

## Limitations

- `time=` is accepted for discord.py familiarity but not scheduled.
- There is no persistence across process restarts.
- `reconnect=True` is stored but reconnect pausing is not yet wired to `DisconnectEvent`.
