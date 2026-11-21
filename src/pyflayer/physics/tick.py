"""Drift-compensated 20 TPS tick loop (M4)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Awaitable, Callable

from pyflayer._internal.clock import Clock

__all__ = ["TickDriver"]

TickCallback = Callable[[int], Awaitable[None]]

# Deadlines are accumulated as floats. Without a tolerance, ``0.05 * 3`` becomes
# ``0.15000000000000002`` and the loop sleeps for an extra tick when the clock is exactly at
# ``0.15``. A nanosecond is far below one tick and only absorbs representation error.
_DEADLINE_EPSILON = 1e-9
#: One minute of samples at 20 TPS is enough to report a stable p99 without unbounded memory.
_INTERVAL_SAMPLES = 1200


class TickDriver:
    """Runs a callback on absolute tick deadlines.

    Deadlines are advanced by exactly ``1 / tps`` seconds, so callback duration does not accumulate
    drift. When the loop falls behind, it runs at most ``max_catch_up`` late ticks and then drops
    the remaining backlog, resynchronizing to the current time. This is what keeps a stalled event
    loop from bursting movement packets ("moved too quickly").

    Attributes:
        clock: The injected time source.
        tps: Target ticks per second (20 for Minecraft).
        max_catch_up: Maximum late ticks to run before dropping the backlog.
        tick: Number of completed callbacks.
        dropped_ticks: Ticks skipped because the loop was more than ``max_catch_up`` behind.
        catch_up_ticks: Ticks that started at least one full interval after their deadline but
            within the catch-up budget. Ordinary sub-millisecond scheduler lateness is excluded.
        catch_up_events: Number of catch-up ticks (same count as :attr:`catch_up_ticks`; kept
            separate for callers that log events rather than ticks).
        jitter: Standard deviation of observed tick intervals, in seconds.
        jitter_ms: :attr:`jitter` in milliseconds.
        jitter_p99_ms: 99th percentile of the absolute deviation from the target interval, in
            milliseconds. This is the roadmap's idle-loop jitter gate.
    """

    __slots__ = (
        "_interval_m2",
        "_interval_mean",
        "_intervals",
        "_last_tick_at",
        "_next",
        "_started_at",
        "_stopped",
        "catch_up_events",
        "catch_up_ticks",
        "clock",
        "dropped_ticks",
        "jitter",
        "max_catch_up",
        "tick",
        "tps",
    )

    def __init__(self, clock: Clock, *, tps: int = 20, max_catch_up: int = 2) -> None:
        if tps <= 0:
            msg = "tps must be positive"
            raise ValueError(msg)
        if max_catch_up < 0:
            msg = "max_catch_up cannot be negative"
            raise ValueError(msg)
        self.clock = clock
        self.tps = tps
        self.max_catch_up = max_catch_up
        self.tick = 0
        self.dropped_ticks = 0
        self.catch_up_ticks = 0
        self.catch_up_events = 0
        self.jitter = 0.0
        self._intervals: deque[float] = deque(maxlen=_INTERVAL_SAMPLES)
        self._next: float | None = None
        self._stopped = False
        self._started_at: float | None = None
        self._last_tick_at: float | None = None
        self._interval_mean = 0.0
        self._interval_m2 = 0.0

    @property
    def interval(self) -> float:
        """Seconds between ticks."""
        return 1.0 / self.tps

    @property
    def jitter_ms(self) -> float:
        """:attr:`jitter` expressed in milliseconds."""
        return self.jitter * 1000.0

    @property
    def jitter_p99_ms(self) -> float:
        """99th percentile absolute deviation from :attr:`interval`, in milliseconds."""
        if not self._intervals:
            return 0.0
        deviations = sorted(abs(sample - self.interval) for sample in self._intervals)
        index = max(0, math.ceil(0.99 * len(deviations)) - 1)
        return deviations[index] * 1000.0

    @property
    def measured_tps(self) -> float:
        """Ticks per second since :meth:`run` started, or ``0.0`` before the first tick."""
        if self._started_at is None or self._last_tick_at is None or self.tick == 0:
            return 0.0
        elapsed = self._last_tick_at - self._started_at
        return self.tick / elapsed if elapsed > 0 else 0.0

    def stop(self) -> None:
        """Ask :meth:`run` to exit after the current callback."""
        self._stopped = True

    async def run(self, callback: TickCallback) -> None:
        """Run ``callback(tick_number)`` until :meth:`stop` is called or the task is cancelled."""
        if self._next is None:
            self._next = self.clock.monotonic() + self.interval
        if self._started_at is None:
            self._started_at = self.clock.monotonic()

        while not self._stopped:
            now = self.clock.monotonic()
            if now + _DEADLINE_EPSILON < self._next:
                await self.clock.sleep_until(self._next)
            if self._stopped:
                break

            now = self.clock.monotonic()
            behind = (now - self._next) / self.interval
            late = behind >= 1.0 - _DEADLINE_EPSILON
            if behind > self.max_catch_up + 1:
                # Keep the newest ``max_catch_up`` ticks and discard the rest of the backlog.
                drop = math.ceil(behind - self.max_catch_up)
                self.dropped_ticks += drop
                self._next += drop * self.interval
            if late:
                self.catch_up_ticks += 1
                self.catch_up_events += 1

            await callback(self.tick)
            completed_at = self.clock.monotonic()
            self._record_interval(completed_at)
            self.tick += 1
            self._next += self.interval

    def _record_interval(self, completed_at: float) -> None:
        previous = self._last_tick_at
        self._last_tick_at = completed_at
        if previous is None:
            return
        delta = completed_at - previous
        self._intervals.append(delta)
        # ``tick`` is the count of callbacks already completed; the first interval is observed
        # between tick 1 and tick 0, so it is sample one of the running variance.
        count = self.tick
        difference = delta - self._interval_mean
        self._interval_mean += difference / count
        self._interval_m2 += difference * (delta - self._interval_mean)
        if count > 1:
            self.jitter = math.sqrt(self._interval_m2 / (count - 1))
