# `pyflayer.ext.tasks`

Recurring coroutines aligned to wall time or physics ticks.

```python
from pyflayer.ext import tasks
```

::: pyflayer.ext.tasks.loop.Loop
    options:
      members:
        - start
        - stop
        - cancel
        - restart
        - change_interval
        - is_running
        - failed
        - is_being_cancelled
        - current_loop
        - before_loop
        - after_loop
        - error

::: pyflayer.ext.tasks.loop.loop

## Semantics

- `ticks=N` waits on `N` `PhysicsTickEvent`s between iterations; without a bot it falls back to
  `N / 20` seconds on the injected clock.
- `seconds` / `minutes` / `hours` use the bot's clock, so `FakeClock` makes them deterministic.
- `count` stops the loop after a fixed number of iterations.
- An exception goes to the `error` handler; without one the loop stops and logs.
- `remove_cog` cancels a cog's loops, so extension reloads do not leak tasks.
