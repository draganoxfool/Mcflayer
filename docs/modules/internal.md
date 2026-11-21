# Internal helpers

`pyflayer._internal` is private. It exists so time, CPU offload and logging have exactly one
implementation.

## Clock (ADR-8)

```python
class Clock(Protocol):
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...
    async def sleep_until(self, deadline: float) -> None: ...
```

- `MonotonicClock` wraps `time.monotonic()` and `asyncio.sleep()`.
- `FakeClock` resolves sleepers **in deadline order** (registration order on ties) when you call
  `advance(dt)`. Use `await clock.advance_async(dt)` to also let awakened tasks run.
- Cancelling a sleeper removes its heap entry (`clock.pending` tells you how many remain).

```python
clock = FakeClock()
task = asyncio.create_task(clock.sleep(0.5))
await clock.advance_async(0.5)
await task
```

## CPU offload

`run_cpu(func, *args, budget_ms=None)` runs synchronous work in a worker thread via
`asyncio.to_thread`. M1 uses it for work that could exceed the ~2 ms loop budget. Per ADR-1, callers
must pass immutable data; loop-owned state is never touched from the worker.

## Logging

Use `logging.getLogger("pyflayer.<module>")`. `configure()` attaches a formatted stderr handler to
the `pyflayer` namespace. Library code never calls `print()`.

## Utilities

`ceil_log2`, `signed(bits)`, `clamp`, `iter_bits`, `batched`, `to_bytes` — small, dependency-free
helpers used by paletted decode and packet code in later milestones.
