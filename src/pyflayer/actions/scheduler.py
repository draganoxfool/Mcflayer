"""Priority/preemption mutex for bot actions.

All arbitration runs under one lock and resources are acquired all-or-nothing, so two actions can
never deadlock by grabbing different halves of a set. Higher priorities preempt cooperatively: the
holder is cancelled, its ``on_preempted``/``checkpoint`` run, its controls are zeroed and the
resources are handed over. ``ABORT`` actions surface ``ActionPreempted``; ``RESUME`` actions retry
from their checkpoint; ``REQUEUE`` actions start again.

Examples:
    >>> handle = bot.scheduler.run(Walk(), priority=Priority.WORK)
    >>> await handle
    >>> bot.scheduler.idle
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.actions.base import (
    Action,
    ActionHandle,
    ActionState,
    HostControls,
    Lease,
    OnPreempt,
    Priority,
    Resource,
)
from pyflayer.errors import (
    ActionBusy,
    ActionCancelled,
    ActionError,
    ActionFailed,
    ActionPreempted,
)
from pyflayer.events.catalog import (
    ActionFinishedEvent,
    ActionPreemptedEvent,
    ActionStartedEvent,
)

__all__ = ["ActionScheduler"]

log = logging.getLogger("pyflayer.actions.scheduler")

_RESOURCE_BITS: tuple[Resource, ...] = (
    Resource.MOVEMENT,
    Resource.LOOK,
    Resource.HANDS,
    Resource.WINDOW,
    Resource.CHAT,
)


class ActionScheduler:
    """Resource arbitration, preemption and lifecycle for actions.

    Args:
        host: Bot-like object implementing the movement/look control surface.
        clock: Injected clock (critical-section grace and timeouts).
        max_critical_s: How long a preemption waits for ``lease.critical()`` to exit.
        preempt_grace: How long the holder's cleanup may take before the lease is force-revoked.
    """

    __slots__ = (
        "_barrier",
        "_barrier_event",
        "_handles",
        "_holders",
        "_lock",
        "_preempt_event",
        "_preempting",
        "_waiters",
        "clock",
        "host",
        "max_critical_s",
        "preempt_grace",
    )

    def __init__(
        self,
        host: HostControls,
        *,
        clock: Clock | None = None,
        max_critical_s: float = 1.0,
        preempt_grace: float = 0.15,
    ) -> None:
        self.host = host
        self.clock = clock or MonotonicClock()
        self.max_critical_s = max_critical_s
        self.preempt_grace = preempt_grace
        self._lock = asyncio.Lock()
        self._holders: dict[Resource, ActionHandle[object]] = {}
        self._waiters: list[ActionHandle[object]] = []
        self._handles: set[ActionHandle[object]] = set()
        self._barrier = False
        self._barrier_event = asyncio.Event()
        self._barrier_event.set()
        self._preempting = 0
        self._preempt_event = asyncio.Event()
        self._preempt_event.set()

    # ------------------------------------------------------------------ public API
    def run(
        self,
        action: Action[object],
        *,
        priority: Priority = Priority.WORK,
        preempt: bool = True,
        queue: bool = False,
        timeout: float | None = None,
    ) -> ActionHandle[object]:
        """Submit ``action`` and return its handle (awaitable)."""
        handle: ActionHandle[object] = ActionHandle(
            action,
            priority,
            action.resources,
            queue=queue,
            timeout=timeout,
            preempt=preempt,
        )
        self._start_handle(handle)
        return handle

    def current(self, resource: Resource | None = None) -> ActionHandle[object] | None:
        """Current holder, or the holder of one resource."""
        if resource is None:
            for handle in self._holders.values():
                return handle
            return None
        for bit in _RESOURCE_BITS:
            if bit & resource and bit in self._holders:
                return self._holders[bit]
        return None

    @property
    def idle(self) -> bool:
        """True when nothing is running, queued or suspended."""
        return not any(not handle.done for handle in self._handles)

    @property
    def active(self) -> tuple[ActionHandle[object], ...]:
        """Running and pending handles."""
        return tuple(handle for handle in self._handles if not handle.done)

    def cancel_all(
        self, *, reason: str = "", below: Priority = Priority.EMERGENCY
    ) -> None:
        """Cancel every action below ``below`` (death barrier, cluster shutdown)."""
        for handle in list(self._handles):
            if handle.done or handle.priority >= below:
                continue
            handle.cancel(reason)

    def set_barrier(self, active: bool) -> None:
        """Stop new actions from starting (death) until :meth:`release_barrier`."""
        self._barrier = active
        if active:
            self._barrier_event.clear()
            self.cancel_all(reason="blocked")
        else:
            self._barrier_event.set()

    def release_barrier(self) -> None:
        """Allow actions again (respawn)."""
        self._barrier = False
        self._barrier_event.set()

    def metrics(self) -> dict[str, object]:
        """Small diagnostic snapshot."""
        return {
            "active": len(self.active),
            "holders": {bit.name: handle.action.name for bit, handle in self._holders.items()},
            "waiters": len(self._waiters),
            "barrier": self._barrier,
        }

    # ------------------------------------------------------------------ internals
    def _start_handle(self, handle: ActionHandle[object]) -> None:
        self._handles.add(handle)
        handle.task = asyncio.create_task(
            self._start(handle), name=f"pyflayer-action-{handle.action.name}"
        )

    async def _start(self, handle: ActionHandle[object]) -> None:
        timer: asyncio.Task[None] | None = None
        if handle.timeout is not None:
            timer = asyncio.create_task(self._timeout(handle, handle.timeout))
        started = self.clock.monotonic()
        try:
            await self._lifecycle(handle)
        except ActionError as exc:
            handle._reject(exc)
        except asyncio.CancelledError:
            if not handle.done:
                handle.state = ActionState.CANCELLED
                handle._reject(self._cancel_error(handle))
        except Exception as exc:  # pragma: no cover - defensive: lifecycle bugs stay local
            log.exception("action lifecycle failed: %s", handle.action.name)
            handle.state = ActionState.FAILED
            handle._reject(ActionFailed(str(exc), action=handle.action.name, error=exc))
        finally:
            if timer is not None:
                timer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer
            self._release(handle)
            self._handles.discard(handle)
            self._emit(
                ActionFinishedEvent(
                    action=handle.action.name,
                    state=handle.state.value,
                    duration=max(0.0, self.clock.monotonic() - started),
                )
            )

    async def _lifecycle(self, handle: ActionHandle[object]) -> None:
        if not handle.inherited:
            await self._acquire(handle)
        while True:
            if handle._cancelled:
                handle.state = ActionState.CANCELLED
                handle._reject(self._cancel_error(handle))
                return
            if handle.checkpoint is not None:
                with contextlib.suppress(Exception):
                    await handle.action.restore(handle.checkpoint)
                handle.checkpoint = None
            lease = Lease(self, handle, handle.resources)
            handle.lease = lease
            handle.state = ActionState.RUNNING
            self._emit(
                ActionStartedEvent(
                    action=handle.action.name,
                    priority=handle.priority.name,
                    resources=handle.resources.value,
                )
            )
            try:
                result = await handle.action.run(lease)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                if handle._cancelled:
                    handle.state = ActionState.CANCELLED
                    handle._reject(self._cancel_error(handle))
                    return
                if handle._preempt_by is None:
                    raise
                by = handle._preempt_by
                await self._after_preempt(handle, lease)
                self._emit(
                    ActionPreemptedEvent(
                        action=handle.action.name,
                        by=by.action.name if by is not None else None,
                    )
                )
                if handle.action.on_preempt is OnPreempt.ABORT:
                    handle.state = ActionState.PREEMPTED
                    handle._reject(
                        ActionPreempted(
                            "preempted", action=handle.action.name, by=handle._preempt_by
                        )
                    )
                    return
                handle._preempt_by = None
                handle.state = ActionState.PENDING
                await self._acquire(handle)
                continue
            except ActionError as exc:
                handle.state = ActionState.FAILED
                handle._reject(exc)
                return
            except Exception as exc:
                handle.state = ActionState.FAILED
                handle._reject(
                    ActionFailed(str(exc), action=handle.action.name, error=exc)
                )
                return
            else:
                handle.state = ActionState.DONE
                handle._resolve(result)
                return

    async def _acquire(self, handle: ActionHandle[object]) -> None:
        while True:
            if handle._cancelled:
                raise self._cancel_error(handle)
            # A resumed action must not steal the lease back from the preemptor.
            while self._preempting:
                await self._preempt_event.wait()
            await self._barrier_event.wait()
            targets: list[ActionHandle[object]] = []
            wait = False
            async with self._lock:
                conflicts = self._conflicts(handle.resources)
                if not conflicts:
                    handle._released.clear()
                    for bit in _RESOURCE_BITS:
                        if bit & handle.resources:
                            self._holders[bit] = handle
                    return
                highest = max((holder.priority for holder in conflicts), default=Priority.IDLE)
                if (
                    handle.preempt
                    and not handle.queue
                    and not handle.inherited
                    and handle.priority > highest
                ):
                    targets = conflicts
                    for target in targets:
                        target._preempt_by = handle
                else:
                    if not handle.queue:
                        raise ActionBusy(
                            "resources are held",
                            action=handle.action.name,
                            holders=[holder.action.name for holder in conflicts],
                        )
                    if handle not in self._waiters:
                        self._waiters.append(handle)
                    handle._wake.clear()
                    wait = True
            if targets:
                await self._preempt_targets(handle, targets)
                continue
            if wait:
                await handle._wake.wait()

    def _conflicts(self, resources: Resource) -> list[ActionHandle[object]]:
        found: list[ActionHandle[object]] = []
        for bit in _RESOURCE_BITS:
            if not bit & resources:
                continue
            holder = self._holders.get(bit)
            if holder is not None and holder not in found:
                found.append(holder)
        return found

    async def _preempt_targets(
        self, handle: ActionHandle[object], targets: list[ActionHandle[object]]
    ) -> None:
        self._preempting += 1
        self._preempt_event.clear()
        try:
            for target in targets:
                await self._wait_for_critical(target)
                target._preempt_by = handle
                task = target.task
                if task is not None and not task.done():
                    task.cancel()
            for target in targets:
                try:
                    await asyncio.wait_for(
                        target._released.wait(), timeout=self.preempt_grace
                    )
                except TimeoutError:
                    log.warning(
                        "forcing lease revocation after preemption grace: %s",
                        target.action.name,
                    )
                    target._revoked = True
                    self._release(target)
                    if target.task is not None and not target.task.done():
                        target.task.cancel()
        finally:
            self._preempting -= 1
            self._preempt_event.set()
            self._wake_waiters()

    async def _wait_for_critical(self, handle: ActionHandle[object]) -> None:
        if handle.lease is None or handle.lease._critical_depth <= 0:
            return
        deadline = self.clock.monotonic() + self.max_critical_s
        while handle.lease is not None and handle.lease._critical_depth > 0:
            if self.clock.monotonic() >= deadline:
                return
            await self.clock.sleep(0.01)

    async def _after_preempt(
        self, handle: ActionHandle[object], lease: Lease
    ) -> None:
        by = handle._preempt_by
        if by is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    handle.action.on_preempted(lease, by), timeout=self.preempt_grace
                )
        if handle.action.on_preempt is OnPreempt.RESUME:
            with contextlib.suppress(Exception):
                handle.checkpoint = await handle.action.checkpoint()
        self._release(handle)

    def _release(self, handle: ActionHandle[object]) -> None:
        released = False
        for bit in _RESOURCE_BITS:
            if self._holders.get(bit) is handle:
                del self._holders[bit]
                released = True
        if handle.lease is not None:
            handle.lease.controls._zero()
            handle.lease = None
        if handle in self._waiters:
            self._waiters.remove(handle)
        handle._released.set()
        if released:
            self._wake_waiters()

    def _emit(self, event: object) -> None:
        bus = getattr(self.host, "events", None)
        if bus is None:
            return
        with contextlib.suppress(Exception):
            bus.dispatch(event)

    def _wake_waiters(self) -> None:
        for waiter in self._waiters:
            waiter._wake.set()

    async def _timeout(self, handle: ActionHandle[object], seconds: float) -> None:
        try:
            await self.clock.sleep(seconds)
        except asyncio.CancelledError:
            raise
        if handle.done:
            return
        handle._timed_out = True
        handle.cancel(f"timed out after {seconds:g}s")

    @staticmethod
    def _cancel_error(handle: ActionHandle[object]) -> ActionError:
        if handle._timed_out:
            return ActionFailed(
                handle._cancel_reason or "timed out", action=handle.action.name
            )
        return ActionCancelled(
            handle._cancel_reason or "cancelled", action=handle.action.name
        )

    def _run_inherited(
        self,
        action: Action[object],
        lease: Lease,
        resources: Resource | None,
    ) -> ActionHandle[object]:
        handle: ActionHandle[object] = ActionHandle(
            action,
            lease.priority,
            lease.resources if resources is None else resources,
            queue=True,
            timeout=None,
            preempt=False,
            inherited=True,
        )
        self._start_handle(handle)
        return handle
