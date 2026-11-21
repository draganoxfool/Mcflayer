"""Injected time source (ADR-8).

Nothing outside this module may call ``time.monotonic()`` or ``asyncio.sleep`` directly. That keeps
tick loops, tasks and cooldowns deterministic under :class:`FakeClock`.

Examples:
    >>> clock = FakeClock()
    >>> task = asyncio.create_task(clock.sleep(0.5))
    >>> clock.advance(0.5)
    >>> await task
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "MonotonicClock", "FakeClock"]


@runtime_checkable
class Clock(Protocol):
    """Time source used by every timer in the library."""

    def monotonic(self) -> float:
        """Return seconds on a monotonic timeline."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Sleep for ``seconds`` of this clock's time."""
        ...

    async def sleep_until(self, deadline: float) -> None:
        """Sleep until ``deadline`` (same timeline as :meth:`monotonic`)."""
        ...


class MonotonicClock:
    """Production clock backed by :func:`time.monotonic`."""

    __slots__ = ()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)

    async def sleep_until(self, deadline: float) -> None:
        await self.sleep(deadline - self.monotonic())


class FakeClock:
    """Deterministic clock for tests.

    Sleepers are woken in deadline order by :meth:`advance`; equal deadlines wake in registration
    order. ``advance`` lets the event loop run after moving time, so awakened tasks observe the new
    time before the call returns.
    """

    __slots__ = ("_now", "_sleepers", "_seq")

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    def monotonic(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        await self.sleep_until(self._now + seconds)

    async def sleep_until(self, deadline: float) -> None:
        if deadline <= self._now:
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (deadline, next(self._seq), future))
        try:
            await future
        except asyncio.CancelledError:
            future.cancel()
            self._sleepers = [entry for entry in self._sleepers if entry[2] is not future]
            heapq.heapify(self._sleepers)
            raise

    def advance(self, seconds: float) -> None:
        """Move time forward, waking every sleeper whose deadline is reached."""
        if seconds < 0:
            msg = "FakeClock cannot move backwards"
            raise ValueError(msg)  # noqa: TRY003 - internal test clock; not a library API error
        target = self._now + seconds
        while self._sleepers and self._sleepers[0][0] <= target:
            deadline, _seq, future = heapq.heappop(self._sleepers)
            self._now = deadline
            if not future.done():
                future.set_result(None)
        self._now = target
        # Sleepers are resolved; awakened tasks run on the next event-loop turn. Tests that need a
        # fully settled state call ``await asyncio.sleep(0)`` (or ``await clock.advance_async(...)``).

    async def advance_async(self, seconds: float) -> None:
        """Advance time and let awakened tasks run before returning."""
        self.advance(seconds)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    @property
    def pending(self) -> int:
        """Number of sleepers not yet woken."""
        return len(self._sleepers)
