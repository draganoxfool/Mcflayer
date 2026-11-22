"""Asynchronous typed event bus.

Semantics (normative, from ARCHITECTURE 2.1):

1. ``dispatch`` is synchronous and never raises into the caller. Waiters registered by
   ``wait_for`` / ``expect`` are resolved first, then listeners run. Internal hooks registered with
   ``priority >= 1000`` run inline (that is how state handlers update the bot before user code);
   every other listener runs in its own tracked task so one slow handler cannot block the bus.
2. A waiter's ``check`` raising fails only that waiter.
3. Listener failures become :class:`~pyflayer.events.catalog.ErrorEvent` (or are logged when no
   error listener exists).
4. ``aclose`` cancels tracked tasks and unsubscribes everything.

Examples:
    >>> bus = EventBus()
    >>> sub = bus.subscribe(ChatEvent, lambda event: None)
    >>> bus.unsubscribe(sub)
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.events.base import Event
from pyflayer.events.catalog import ErrorEvent

__all__ = ["EventBus", "Expectation", "Subscription"]

log = logging.getLogger("pyflayer.events.bus")

Listener = Callable[[Any], Any]


@dataclass(slots=True)
class Subscription:
    """A registered listener.

    Attributes:
        event: Event class being observed.
        listener: Callable invoked with the event instance.
        priority: Higher runs earlier; ``>= 1000`` runs inline during dispatch.
        once: Unsubscribe after the first dispatch.
        owner: Optional owner token used by cogs/extensions for bulk unsubscribe.
    """

    event: type[Event]
    listener: Listener
    priority: int = 0
    once: bool = False
    owner: object | None = None
    id: int = 0
    active: bool = True

    def __repr__(self) -> str:
        return (
            f"Subscription(event={self.event.__name__}, priority={self.priority}, once={self.once})"
        )


@dataclass(slots=True)
class _Waiter:
    event: type[Event]
    future: asyncio.Future[Any]
    check: Callable[[Any], bool] | None


class EventBus:
    """Typed event bus with priority ordering, waiters and streams.

    Args:
        clock: Injected clock used for ``timeout`` values.
        on_error: Optional synchronous consumer for listener exceptions. When absent, errors are
            dispatched as :class:`ErrorEvent` and logged if nobody listens.
    """

    __slots__ = ("_closed", "_ids", "_subs", "_tasks", "_waiters", "clock", "on_error")

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        on_error: Callable[[Event, Subscription, BaseException], None] | None = None,
    ) -> None:
        self.clock = clock or MonotonicClock()
        self.on_error = on_error
        self._subs: list[Subscription] = []
        self._waiters: list[_Waiter] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._ids = itertools.count(1)
        self._closed = False

    # ------------------------------------------------------------------ registration
    def subscribe(
        self,
        event: type[Event],
        listener: Listener,
        *,
        priority: int = 0,
        once: bool = False,
        owner: object | None = None,
    ) -> Subscription:
        """Register ``listener`` for ``event``.

        Raises:
            RuntimeError: When the bus has been closed.
        """
        if self._closed:
            raise RuntimeError("EventBus is closed")
        subscription = Subscription(
            event=event,
            listener=listener,
            priority=priority,
            once=once,
            owner=owner,
            id=next(self._ids),
        )
        self._subs.append(subscription)
        self._subs.sort(key=lambda sub: (-sub.priority, sub.id))
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        """Remove a subscription. Unknown subscriptions are ignored."""
        subscription.active = False
        with suppress(ValueError):
            self._subs.remove(subscription)

    def unsubscribe_owner(self, owner: object) -> int:
        """Remove every subscription registered by ``owner``; return the count removed."""
        removed = [sub for sub in self._subs if sub.owner is owner]
        for sub in removed:
            self.unsubscribe(sub)
        return len(removed)

    def has_listeners(self, event: type[Event]) -> bool:
        """True when at least one listener is registered for ``event``."""
        return any(sub.event is event for sub in self._subs)

    @property
    def subscription_count(self) -> int:
        """Number of live subscriptions."""
        return len(self._subs)

    @property
    def task_count(self) -> int:
        """Number of listener tasks still running."""
        return len(self._tasks)

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, event: Event) -> None:
        """Deliver `event` synchronously; never raises into the caller."""
        if self._closed:
            return
        subscriptions = tuple(self._subs)
        # Internal state hooks run before waiters and user listeners (ADR-4).
        for subscription in subscriptions:
            if subscription.priority >= 1000:
                self._deliver(event, subscription)
        self._resolve_waiters(event)
        for subscription in subscriptions:
            if subscription.priority < 1000:
                self._deliver(event, subscription)

    def _deliver(self, event: Event, subscription: Subscription) -> None:
        if not subscription.active:
            return
        if subscription.event is not event.__class__ and not isinstance(event, subscription.event):
            return
        if subscription.once:
            self.unsubscribe(subscription)
        try:
            result = subscription.listener(event)
        except Exception as exc:
            self._listener_error(event, subscription, exc)
            return
        if inspect.isawaitable(result):
            self._spawn(result, event, subscription)

    def _spawn(self, awaitable: Any, event: Event, subscription: Subscription) -> None:
        task = asyncio.ensure_future(awaitable)
        self._tasks.add(task)

        def _done(finished: asyncio.Task[Any]) -> None:
            self._tasks.discard(finished)
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None:
                self._listener_error(event, subscription, exc)

        task.add_done_callback(_done)

    def _listener_error(self, event: Event, subscription: Subscription, exc: BaseException) -> None:
        if self.on_error is not None:
            try:
                self.on_error(event, subscription, exc)
            except Exception:
                log.exception("EventBus on_error handler raised")
            return
        if isinstance(event, ErrorEvent):
            log.error("event listener failed", exc_info=exc)
            return
        log.warning(
            "event listener %r failed for %s: %s",
            subscription.listener,
            event.__class__.__name__,
            exc,
        )
        self.dispatch(ErrorEvent(event=event, listener=subscription.listener, exception=exc))

    def _resolve_waiters(self, event: Event) -> None:
        if not self._waiters:
            return
        remaining: list[_Waiter] = []
        for waiter in self._waiters:
            if not isinstance(event, waiter.event):
                remaining.append(waiter)
                continue
            if waiter.future.done():
                continue
            if waiter.check is not None:
                try:
                    matched = bool(waiter.check(event))
                except Exception as exc:
                    waiter.future.set_exception(exc)
                    continue
                if not matched:
                    remaining.append(waiter)
                    continue
            waiter.future.set_result(event)
        self._waiters = remaining

    # ------------------------------------------------------------------ awaiting
    def _register_waiter(self, event: type[Event], check: Callable[[Any], bool] | None) -> _Waiter:
        """Register a waiter synchronously, before any event can be dispatched."""
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        waiter = _Waiter(event=event, future=future, check=check)
        self._waiters.append(waiter)
        return waiter

    async def _await_waiter(self, waiter: _Waiter, timeout_seconds: float | None) -> Any:
        timer: asyncio.Task[None] | None = None
        if timeout_seconds is not None:
            deadline = self.clock.monotonic() + timeout_seconds
            timer = asyncio.ensure_future(self._expire(waiter.future, deadline, waiter.event))
        try:
            return await waiter.future
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            if timer is not None:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)

    async def wait_for(
        self,
        event: type[Event],
        *,
        check: Callable[[Any], bool] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - public event-wait API
    ) -> Any:
        """Wait for the next matching ``event``.

        Raises:
            TimeoutError: When ``timeout`` elapses on the injected clock.
        """
        waiter = self._register_waiter(event, check)
        return await self._await_waiter(waiter, timeout)

    async def _expire(
        self, future: asyncio.Future[Any], deadline: float, event: type[Event]
    ) -> None:
        try:
            await self.clock.sleep_until(deadline)
        except asyncio.CancelledError:
            raise
        if not future.done():
            future.set_exception(TimeoutError(f"timed out waiting for {event.__name__}"))

    def expect(
        self,
        event: type[Event],
        *,
        check: Callable[[Any], bool] | None = None,
        timeout: float | None = None,
    ) -> Expectation:
        """Register a waiter before running an action, so the event cannot be missed.

        Returns:
            An :class:`Expectation` usable as an async context manager and as an awaitable.
            ``await expectation`` only inside the context.
        """
        return Expectation(self, event, check=check, timeout=timeout)

    def stream(self, event: type[Event], *, maxsize: int = 256) -> _EventStream:
        """Create a lazy event stream.

        Use the stream as an async context manager for reliable cleanup when iteration stops early.
        Plain async iteration remains supported; call ``aclose`` to unsubscribe explicitly.
        The queue is bounded; when full, the oldest event is dropped and ``dropped`` increments.
        """
        return _EventStream(self, event, maxsize=maxsize)

    async def aclose(self) -> None:
        """Cancel listener tasks and remove all subscriptions and waiters."""
        self._closed = True
        for waiter in self._waiters:
            if not waiter.future.done():
                waiter.future.cancel()
        self._waiters.clear()
        self._subs.clear()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


class Expectation:
    """Deferred waiter created by :meth:`EventBus.expect`.

    The waiter is registered on ``__aenter__`` and the result is awaited by ``await``.
    """

    __slots__ = ("_bus", "_check", "_event", "_task", "_timeout", "_waiter")

    def __init__(
        self,
        bus: EventBus,
        event: type[Event],
        *,
        check: Callable[[Any], bool] | None = None,
        timeout: float | None = None,
    ) -> None:
        self._bus = bus
        self._event = event
        self._check = check
        self._timeout = timeout
        self._task: asyncio.Task[Any] | None = None
        self._waiter: _Waiter | None = None

    async def __aenter__(self) -> Expectation:
        # Registration is synchronous so an event dispatched immediately afterwards is caught.
        self._waiter = self._bus._register_waiter(self._event, self._check)
        self._task = asyncio.ensure_future(self._bus._await_waiter(self._waiter, self._timeout))
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        del exc, tb
        if self._task is None or self._task.done():
            return False
        if exc_type is None and self._waiter is not None and self._waiter.future.done():
            # The dispatcher already resolved the waiter; let the task deliver the result.
            await self._task
            return False
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        return False

    def __await__(self) -> Any:
        if self._task is None:
            raise RuntimeError("expectation awaited before entering its context")
        return self._task.__await__()


class _EventStream:
    """Async iterator backed by a bounded queue."""

    __slots__ = ("_bus", "_event", "_maxsize", "_queue", "_sub", "dropped")

    def __init__(self, bus: EventBus, event: type[Event], *, maxsize: int) -> None:
        self._bus = bus
        self._event = event
        self._maxsize = max(1, maxsize)
        self._queue: asyncio.Queue[Any] | None = None
        self._sub: Subscription | None = None
        self.dropped = 0

    def __aiter__(self) -> _EventStream:
        return self

    async def __aenter__(self) -> _EventStream:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        await self.aclose()

    async def __anext__(self) -> Any:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._maxsize)
            self._sub = self._bus.subscribe(self._event, self._offer)
        return await self._queue.get()

    def _offer(self, event: Event) -> None:
        assert self._queue is not None
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(event)

    async def aclose(self) -> None:
        """Unsubscribe from the event bus.

        Async iteration does not call this automatically; use ``async with`` for scoped cleanup.
        """
        if self._sub is not None:
            self._bus.unsubscribe(self._sub)
            self._sub = None

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        sub = getattr(self, "_sub", None)
        if sub is not None:
            with suppress(Exception):
                self._bus.unsubscribe(sub)
