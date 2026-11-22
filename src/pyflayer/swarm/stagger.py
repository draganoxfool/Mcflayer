"""Throttle-aware login staggering for bot clusters.

Minecraft servers (Spigot/Paper and most proxies) limit how many clients may connect from one IP
within a short window (``connection-throttle``, 4000 ms by default). A swarm that opens every login
at once is kicked with "connection throttled" or "logging in too fast". :class:`LoginStaggerPolicy`
serializes logins with a configurable minimum interval, adds jitter, limits in-flight logins and
backs off when the server reports a throttle kick.

Examples:
    >>> policy = LoginStaggerPolicy(min_interval=4.0)
    >>> async def login(bot):
    ...     async with policy.slot():
    ...         await bot.connect()
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import AsyncIterator

from pyflayer._internal.clock import Clock, MonotonicClock

__all__ = ["LoginStaggerPolicy"]

#: Kick reasons that mean "slow down" rather than "this bot is banned".
_THROTTLE_MARKERS = (
    "connection throttled",
    "throttl",
    "too fast",
    "logging in too",
    "already connected",
    "try again later",
)


class LoginStaggerPolicy:
    """Spaces out logins and backs off after throttle kicks.

    Args:
        min_interval: Seconds between two login starts (default 4 s, the Spigot/Paper throttle).
        max_interval: Upper bound after repeated throttle kicks.
        jitter: Maximum random extra delay added after each login start, in seconds.
        max_concurrency: Maximum logins held open at the same time. Keep at ``1`` for vanilla
            servers; a proxy that throttles per connection can use more.
        clock: Injected clock used for every wait.
        rng: Random source for jitter (inject a seeded ``random.Random`` in tests).

    Attributes:
        min_interval: Configured base interval.
        max_concurrency: Login concurrency cap.
    """

    __slots__ = (
        "_in_flight",
        "_lock",
        "_multiplier",
        "_next_at",
        "_semaphore",
        "clock",
        "jitter",
        "max_concurrency",
        "max_interval",
        "min_interval",
        "rng",
    )

    def __init__(
        self,
        min_interval: float = 4.0,
        *,
        max_interval: float = 60.0,
        jitter: float = 0.5,
        max_concurrency: int = 1,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval cannot be negative")
        if max_interval < min_interval:
            raise ValueError("max_interval must be >= min_interval")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.jitter = max(0.0, jitter)
        self.max_concurrency = max_concurrency
        self.clock = clock or MonotonicClock()
        self.rng = rng or random.Random()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._next_at = 0.0
        self._multiplier = 1.0
        self._in_flight = 0

    @property
    def interval(self) -> float:
        """Current spacing between login starts, including throttle backoff."""
        return min(self.max_interval, self.min_interval * self._multiplier)

    @property
    def in_flight(self) -> int:
        """Logins currently inside :meth:`slot`."""
        return self._in_flight

    @property
    def multiplier(self) -> float:
        """Backoff multiplier applied to :attr:`min_interval`."""
        return self._multiplier

    @staticmethod
    def is_throttle_reason(reason: str) -> bool:
        """True when a kick reason looks like rate limiting rather than a ban."""
        lowered = reason.lower()
        return any(marker in lowered for marker in _THROTTLE_MARKERS)

    def record_throttle(self, reason: str = "") -> float:
        """Double the interval after a throttle-style kick; return the new interval.

        A non-throttle kick (ban, whitelist, server full) does not change the policy.
        """
        if reason and not self.is_throttle_reason(reason):
            return self.interval
        self._multiplier = min(8.0, self._multiplier * 2.0)
        return self.interval

    def record_success(self) -> None:
        """Return to the configured base interval after a successful login."""
        self._multiplier = 1.0

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Reserve a login slot, wait out the spacing, then hold the concurrency permit.

        Use around the login handshake only::

            async with policy.slot():
                await bot.connect()
        """
        async with self._lock:
            now = self.clock.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await self.clock.sleep(wait)
            delay = self.interval
            if self.jitter:
                delay += self.rng.uniform(0.0, self.jitter)
            self._next_at = self.clock.monotonic() + delay
        await self._semaphore.acquire()
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
            self._semaphore.release()
