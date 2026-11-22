# Internal helpers

`pyflayer._internal` contains private clock, CPU-offload, logging, and utility modules used by the
public packages.

## Clock (ADR-8)

```python
class Clock(Protocol):
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...
    async def sleep_until(self, deadline: float) -> None: ...
```

- `MonotonicClock` wraps `time.monotonic()` and `asyncio.sleep()`.
- `FakeClock` resolves sleepers in deadline order (registration order on ties) when you call
  `advance(dt)`. Use `await clock.advance_async(dt)` to let awakened tasks run before returning.
- Cancelling a sleeper removes its heap entry (`clock.pending` tells you how many remain).

```python
clock = FakeClock()
task = asyncio.create_task(clock.sleep(0.5))
await clock.advance_async(0.5)
await task
```

## CPU offload

`run_cpu(func, *args, budget_ms=None, **kwargs)` runs a synchronous callable in a worker thread via
`asyncio.to_thread` and returns its result. If the optional soft time budget is exceeded, it logs a
warning. Callers should pass data that the worker can safely access without mutating event-loop-owned
state.

## Logging

Use `logging.getLogger("pyflayer.<module>")`. `configure()` attaches a formatted stderr handler to
the `pyflayer` namespace. Library code never calls `print()`.

## Utilities

The private utility module contains helpers such as `ceil_log2`, `signed`, `clamp`, `iter_bits`,
`batched`, and `to_bytes`.
