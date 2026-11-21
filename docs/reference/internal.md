# `pyflayer._internal`

Internal utilities, clocks, and implementation details. These are not part of the public API
surface but are documented here for completeness and advanced usage.

```python
from pyflayer._internal.clock import MonotonicClock, Clock
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer._internal.clock
    options:
      show_root_heading: false
      show_root_toc_entry: false

## Clock

Base interface for time sources.

```python
from pyflayer._internal.clock import Clock, MonotonicClock, FakeClock
```

### `Clock` (abstract)

The base clock interface used throughout PyFlayer. Injecting a custom clock allows deterministic
testing with `FakeClock` and custom time semantics in production.

**Methods**

| Method | Meaning |
|---|---|
| `monotonic()` | Current time on a monotonic timeline |
| `sleep(seconds)` | Sleep for a duration on this clock |
| `sleep_until(deadline)` | Sleep until an absolute deadline |

### `MonotonicClock`

A clock based on `time.monotonic()`. Suitable for production use. It provides real-time
progression and is the default clock used by `Bot`.

### `FakeClock`

A deterministic clock for testing. Advances time in controlled steps via `advance(seconds)`.
Useful for testing physics engines, action schedulers, and reconnect logic without wall-time
drift.

**Methods / properties**

| Member | Meaning |
|---|---|
| `advance(seconds)` | Advance the clock and wake sleepers whose deadline is reached |
| `advance_async(seconds)` | Advance and yield so awakened tasks run |
| `pending` | Number of sleepers not yet woken |
| `monotonic()` | Current deterministic time |

## Quick example — deterministic physics test

```python
import asyncio

from pyflayer._internal.clock import FakeClock
from pyflayer.data import McData
from pyflayer.models import Vec3
from pyflayer.physics import ControlState, PhysicsEngine, PlayerState
from pyflayer.world import World

clock = FakeClock()
mc = McData.load("1.8.9")
world = World(mc)
engine = PhysicsEngine()

state = PlayerState(Vec3(0.0, 64.0, 0.0), on_ground=True)
tasks = []


async def tick(n):
    global state
    state = engine.step(state, ControlState(forward=1.0), world)
    tasks.append((n, state.position.copy()))
    clock.advance(1.0 / 20.0)  # 20 TPS


async def main():
    await asyncio.sleep(0)  # ensure loop runs
    for i in range(20):
        await tick(i)
    print(f"Position after 1s: {state.position}")


asyncio.run(main())
```