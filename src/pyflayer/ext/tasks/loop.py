"""``tasks.loop``: recurring coroutines driven by wall time or physics ticks.

``Loop`` is a descriptor. Declared inside a :class:`~pyflayer.ext.commands.cog.Cog`, it binds to the
cog instance and uses ``cog.bot`` for its clock, readiness and physics-tick source. ``ticks=``
synchronises iterations to the bot's :class:`~pyflayer.events.catalog.PhysicsTickEvent` counter
instead of wall time.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from pyflayer.events.catalog import PhysicsTickEvent

__all__ = ["Loop", "loop", "MISSING"]

log = logging.getLogger("pyflayer.ext.tasks")

MISSING = object()
_MISSING = MISSING


def _as_seconds(*, seconds: object, minutes: object, hours: object) -> float | None:
    provided = [
        1.0 if seconds is not MISSING else None,
        1.0 if minutes is not MISSING else None,
        1.0 if hours is not MISSING else None,
    ]
    if sum(1 for value in provided if value) > 1:
        raise TypeError("specify at most one of seconds, minutes or hours")
    if seconds is not MISSING:
        return float(seconds)  # type: ignore[arg-type]
    if minutes is not MISSING:
        return float(minutes) * 60.0  # type: ignore[arg-type]
    if hours is not MISSING:
        return float(hours) * 3600.0  # type: ignore[arg-type]
    return None


class Loop:
    """A recurring coroutine declaration.

    Args:
        seconds: Wall-clock interval in seconds; at most one unit may be given.
        minutes: Wall-clock interval in minutes.
        hours: Wall-clock interval in hours.
        ticks: Run once per this many physics ticks (Minecraft-native).
        count: Stop after this many iterations (``None`` runs forever).
        reconnect: Pause and resume when the connection is lost.
        name: Optional name used in logs.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        seconds: object = MISSING,
        minutes: object = MISSING,
        hours: object = MISSING,
        ticks: int | None = None,
        count: int | None = None,
        reconnect: bool = True,
        name: str | None = None,
    ) -> None:
        self.func = func
        self.seconds = _as_seconds(seconds=seconds, minutes=minutes, hours=hours)
        self.ticks = ticks
        self.count = count
        self.reconnect = reconnect
        self.name = name or getattr(func, "__name__", "loop")
        self._before: Callable[..., Any] | None = None
        self._after: Callable[..., Any] | None = None
        self._error: Callable[..., Any] | None = None
        self._resume_flag = False
        self._cache_key = f"__pyflayer_loop_{id(self)}"
        self._standalone: _BoundLoop | None = None
        if inspect.iscoroutinefunction(func) is False:
            raise TypeError("tasks.loop requires an async function")

    def __get__(self, instance: Any, owner: type | None = None) -> _BoundLoop:
        if instance is None:
            return self._standalone_bound()
        # A bound loop must be stable for the cog instance: stop()/cancel() and remove_cog()
        # must reach the same task that start() created.
        cache = instance.__dict__
        bound = cache.get(self._cache_key)
        if bound is None:
            bound = _BoundLoop(self, instance)
            cache[self._cache_key] = bound
        return bound

    def _standalone_bound(self) -> _BoundLoop:
        if self._standalone is None:
            self._standalone = _BoundLoop(self, None)
        return self._standalone

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = self.name or name

    # ------------------------------------------------------------------ standalone lifecycle
    @property
    def current_loop(self) -> int:
        """Completed iterations (for a loop used outside a cog)."""
        return self._standalone_bound().current_loop

    def start(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Start a standalone loop; returns the backing task."""
        return self._standalone_bound().start(*args, **kwargs)

    def stop(self) -> None:
        """Stop a standalone loop after the current iteration."""
        self._standalone_bound().stop()

    def cancel(self) -> None:
        """Cancel a standalone loop immediately."""
        self._standalone_bound().cancel()

    def restart(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Cancel and restart a standalone loop."""
        return self._standalone_bound().restart(*args, **kwargs)

    def change_interval(self, **kwargs: Any) -> None:
        """Update the interval of a standalone loop in place."""
        self._standalone_bound().change_interval(**kwargs)

    def is_running(self) -> bool:
        """True while a standalone loop's task is live."""
        return self._standalone_bound().is_running()

    def failed(self) -> bool:
        """True after an unhandled error stopped a standalone loop."""
        return self._standalone_bound().failed()

    def is_being_cancelled(self) -> bool:
        """True while a standalone loop's cancellation is in progress."""
        return self._standalone_bound().is_being_cancelled()

    # ------------------------------------------------------------------ hooks
    def before_loop(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook awaited before the first iteration."""
        self._before = coro
        return coro

    def after_loop(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook awaited after the loop stops."""
        self._after = coro
        return coro

    def error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register an exception handler."""
        self._error = coro
        return coro


class _BoundLoop:
    """A :class:`Loop` bound to one cog instance (or to nothing for a standalone loop)."""

    __slots__ = ("_loop", "_instance", "_task", "_cancelled", "_failed", "_current_loop")

    def __init__(self, loop: Loop, instance: Any) -> None:
        self._loop = loop
        self._instance = instance
        self._task: asyncio.Task[None] | None = None
        self._cancelled = False
        self._failed = False
        self._current_loop = 0

    # ------------------------------------------------------------------ introspection
    @property
    def name(self) -> str:
        return self._loop.name

    @property
    def current_loop(self) -> int:
        """Completed iterations."""
        return self._current_loop

    @property
    def bot(self) -> Any:
        if self._instance is None:
            return None
        return getattr(self._instance, "bot", self._instance)

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def failed(self) -> bool:
        return self._failed

    def is_being_cancelled(self) -> bool:
        return self._task is not None and self._task.cancelling() > 0

    # ------------------------------------------------------------------ lifecycle
    def start(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Start the loop; returns the backing task."""
        if self.is_running():
            raise RuntimeError(f"loop {self.name!r} is already running")
        self._cancelled = False
        self._failed = False
        self._loop._resume_flag = True
        self._task = asyncio.create_task(
            self._run(*args, **kwargs), name=f"pyflayer-loop-{self.name}"
        )
        return self._task

    def stop(self) -> None:
        """Ask the loop to finish the current iteration and stop."""
        self._cancelled = True
        self._loop._resume_flag = False

    def cancel(self) -> None:
        """Cancel the loop task immediately."""
        self._cancelled = True
        self._loop._resume_flag = False
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def restart(self, *args: Any, **kwargs: Any) -> asyncio.Task[None]:
        """Cancel and start again."""
        self.cancel()
        self._task = None
        return self.start(*args, **kwargs)

    def change_interval(self, **kwargs: Any) -> None:
        """Update the interval in place."""
        self._loop.seconds = _as_seconds(
            seconds=kwargs.get("seconds", MISSING),
            minutes=kwargs.get("minutes", MISSING),
            hours=kwargs.get("hours", MISSING),
        )
        if "ticks" in kwargs:
            self._loop.ticks = kwargs["ticks"]

    def _resume(self) -> None:
        """Restart after a cog reload when the loop was previously started."""
        if self._loop._resume_flag and not self.is_running():
            self.start()

    # ------------------------------------------------------------------ run loop
    async def _run(self, *args: Any, **kwargs: Any) -> None:
        loop = self._loop
        bound = loop.func.__get__(self._instance, type(self._instance)) if self._instance else loop.func
        try:
            if loop._before is not None:
                result = loop._before(self)
                if inspect.isawaitable(result):
                    await result
            while not self._cancelled:
                if loop.count is not None and self._current_loop >= loop.count:
                    break
                self._current_loop += 1
                try:
                    result = bound(*args, **kwargs)
                    if inspect.isawaitable(result):
                        await result
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - routed to the error handler
                    if loop._error is not None:
                        handled = loop._error(self, exc)
                        if inspect.isawaitable(handled):
                            await handled
                    else:
                        self._failed = True
                        log.exception("loop %s failed", loop.name)
                        break
                if loop.count is not None and self._current_loop >= loop.count:
                    break
                await self._wait_next()
        except asyncio.CancelledError:
            raise
        finally:
            if not self._cancelled and loop._after is not None:
                result = loop._after(self)
                if inspect.isawaitable(result):
                    await result
            # A naturally finished loop (count reached, error without handler) should not
            # be resurrected the next time its cog is added.
            if not self._cancelled:
                loop._resume_flag = False

    async def _wait_next(self) -> None:
        loop = self._loop
        bot = self.bot
        if loop.ticks:
            if bot is not None and hasattr(bot, "wait_for"):
                for _ in range(loop.ticks):
                    await bot.wait_for(PhysicsTickEvent)
                return
            clock = getattr(bot, "clock", None)
            if clock is not None:
                await clock.sleep(loop.ticks / 20.0)
            else:
                await asyncio.sleep(loop.ticks / 20.0)
            return
        delay = loop.seconds if loop.seconds is not None else 0.0
        clock = getattr(bot, "clock", None)
        if clock is not None:
            await clock.sleep(delay)
        else:
            await asyncio.sleep(delay)

    def __repr__(self) -> str:
        return f"<Loop {self.name!r} running={self.is_running()} iterations={self._current_loop}>"


def loop(
    *,
    seconds: object = MISSING,
    minutes: object = MISSING,
    hours: object = MISSING,
    ticks: int | None = None,
    time: object = MISSING,
    count: int | None = None,
    reconnect: bool = True,
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Loop]:
    """Declare a recurring coroutine.

    ``time=`` is accepted for discord.py familiarity but is not scheduled; use ``seconds``,
    ``minutes``, ``hours`` or ``ticks``.
    """
    del time

    def decorator(func: Callable[..., Any]) -> Loop:
        return Loop(
            func,
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            ticks=ticks,
            count=count,
            reconnect=reconnect,
            name=name,
        )

    return decorator
