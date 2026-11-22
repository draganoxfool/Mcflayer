"""Action primitives: resources, priorities, leases and handles.

The scheduler is the only writer of bot controls. An action receives a :class:`Lease`; writing
through ``lease.controls`` after the lease was revoked raises
:class:`~pyflayer.errors.LeaseRevoked`, and revoking zeroes the controls the lease had set.

Examples:
    >>> class Walk(Action[str]):
    ...     resources = Resource.MOVEMENT
    ...     name = "walk"
    ...     async def run(self, lease):
    ...         lease.controls.set(forward=1.0)
    ...         return "walking"
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from enum import Flag as _Flag
from enum import IntEnum, StrEnum, auto
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Protocol, TypeVar, cast

from pyflayer.errors import LeaseRevoked

if TYPE_CHECKING:
    from pyflayer.actions.scheduler import ActionScheduler

__all__ = [
    "Action",
    "ActionHandle",
    "ActionState",
    "ControlHandle",
    "Lease",
    "OnPreempt",
    "Priority",
    "Resource",
]

R = TypeVar("R")


class Resource(_Flag):
    """Capabilities an action may require."""

    NONE = 0
    MOVEMENT = auto()
    LOOK = auto()
    HANDS = auto()
    WINDOW = auto()
    CHAT = auto()


class Priority(IntEnum):
    """Scheduler priority classes (higher wins)."""

    IDLE = 0
    BACKGROUND = 10
    WORK = 20
    USER = 30
    COMBAT = 60
    SURVIVAL = 90
    EMERGENCY = 100


class OnPreempt(StrEnum):
    """What happens to an action when a higher priority action takes over."""

    ABORT = "abort"
    RESUME = "resume"
    REQUEUE = "requeue"


class ActionState(StrEnum):
    """Lifecycle of an :class:`ActionHandle`."""

    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    DONE = "done"
    CANCELLED = "cancelled"
    PREEMPTED = "preempted"
    FAILED = "failed"


class HostControls(Protocol):
    """Control surface the lease writes to (implemented by ``Bot``)."""

    def set_movement(
        self,
        forward: float = 0.0,
        strafe: float = 0.0,
        *,
        sprint: bool = False,
        sneak: bool = False,
    ) -> None: ...

    def stop_movement(self) -> None: ...

    def look(self, *, yaw: float | None = None, pitch: float | None = None) -> None: ...

    def jump(self) -> None: ...


class Action(Generic[R]):
    """One schedulable behaviour.

    Attributes:
        resources: Resources the scheduler must acquire.
        name: Human-readable name used by events, errors and logs.
        on_preempt: Abort, resume from ``checkpoint()``, or requeue after a preemption.
    """

    resources: ClassVar[Resource] = Resource.NONE
    name: ClassVar[str] = "action"
    on_preempt: ClassVar[OnPreempt] = OnPreempt.ABORT

    async def run(self, lease: Lease) -> R:
        """Perform the work. Use only ``lease.controls`` for movement/look."""
        raise NotImplementedError

    async def on_preempted(self, lease: Lease, by: ActionHandle[Any]) -> None:
        """Fast cleanup after preemption (at most one tick of work)."""
        return None

    async def checkpoint(self) -> object | None:
        """Return the state needed to resume after preemption."""
        return None

    async def restore(self, checkpoint: object | None) -> None:
        """Restore state produced by :meth:`checkpoint` before a resumed run."""
        del checkpoint

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"


@dataclass(frozen=True, slots=True)
class _ControlWrite:
    forward: float = 0.0
    strafe: float = 0.0
    sprint: bool = False
    sneak: bool = False


class ControlHandle:
    """Write-only movement/look capability tied to one lease."""

    __slots__ = ("_last", "lease")

    def __init__(self, lease: Lease) -> None:
        self.lease = lease
        self._last = _ControlWrite()

    def _check(self) -> None:
        if self.lease.revoked:
            raise LeaseRevoked("lease was revoked", action=self.lease.handle.action.name)

    def set(
        self,
        forward: float = 0.0,
        strafe: float = 0.0,
        *,
        sprint: bool = False,
        sneak: bool = False,
    ) -> None:
        """Set continuous movement input for the next physics tick."""
        self._check()
        self._last = _ControlWrite(forward, strafe, sprint, sneak)
        self.lease.scheduler.host.set_movement(
            forward, strafe, sprint=sprint, sneak=sneak
        )

    def look(self, yaw: float, pitch: float = 0.0) -> None:
        """Set the look direction used by the next physics tick."""
        self._check()
        self.lease.scheduler.host.look(yaw=yaw, pitch=pitch)

    def jump(self) -> None:
        """Request one jump on the next physics tick."""
        self._check()
        self.lease.scheduler.host.jump()

    def stop(self) -> None:
        """Clear movement input."""
        self._check()
        self._last = _ControlWrite()
        self.lease.scheduler.host.stop_movement()

    def _zero(self) -> None:
        self._last = _ControlWrite()
        with contextlib.suppress(Exception):
            self.lease.scheduler.host.stop_movement()


class Lease:
    """Capability token handed to :meth:`Action.run`."""

    __slots__ = ("_critical_depth", "controls", "handle", "resources", "scheduler")

    def __init__(
        self,
        scheduler: ActionScheduler,
        handle: ActionHandle[Any],
        resources: Resource,
    ) -> None:
        self.scheduler = scheduler
        self.handle = handle
        self.resources = resources
        self.controls = ControlHandle(self)
        self._critical_depth = 0

    @property
    def priority(self) -> Priority:
        """Priority of the owning action."""
        return self.handle.priority

    @property
    def revoked(self) -> bool:
        """True once the scheduler took the lease away."""
        return self.handle.state is not ActionState.RUNNING or self.handle.lease is not self

    @contextlib.asynccontextmanager
    async def critical(self) -> AsyncIterator[None]:
        """Defer preemption while a multi-packet operation is in flight."""
        self._critical_depth += 1
        try:
            yield
        finally:
            self._critical_depth -= 1

    def look(self, yaw: float, pitch: float = 0.0) -> None:
        """Set the look direction through this lease's controls."""
        self.controls.look(yaw, pitch)

    def jump(self) -> None:
        """Request one jump through this lease's controls."""
        self.controls.jump()

    def child(
        self, action: Action[R], *, resources: Resource | None = None
    ) -> ActionHandle[R]:
        """Run ``action`` under this lease without re-acquiring resources."""
        return cast(
            "ActionHandle[R]",
            self.scheduler._run_inherited(
                cast("Action[object]", action), self, resources
            ),
        )

    def __repr__(self) -> str:
        return f"Lease(resources={self.resources!r}, priority={self.priority.name})"


class ActionHandle(Generic[R], Awaitable[R]):
    """A submitted action; await it for the result or cancel it."""

    __slots__ = (
        "_cancel_reason",
        "_cancelled",
        "_critical_depth",
        "_future",
        "_preempt_by",
        "_released",
        "_revoked",
        "_timed_out",
        "_wake",
        "action",
        "checkpoint",
        "inherited",
        "lease",
        "preempt",
        "priority",
        "queue",
        "resources",
        "state",
        "task",
        "timeout",
    )

    def __init__(
        self,
        action: Action[R],
        priority: Priority,
        resources: Resource,
        *,
        queue: bool,
        timeout: float | None,
        preempt: bool = True,
        inherited: bool = False,
    ) -> None:
        self.action = action
        self.priority = priority
        self.resources = resources
        self.queue = queue
        self.timeout = timeout
        self.preempt = preempt
        self.inherited = inherited
        self.state = ActionState.PENDING
        self.task: asyncio.Task[None] | None = None
        self.lease: Lease | None = None
        self.checkpoint: object | None = None
        self._future: asyncio.Future[R] = asyncio.get_running_loop().create_future()
        self._released = asyncio.Event()
        self._wake = asyncio.Event()
        self._preempt_by: ActionHandle[Any] | None = None
        self._cancelled = False
        self._cancel_reason = ""
        self._timed_out = False
        self._revoked = False
        self._critical_depth = 0

    @property
    def done(self) -> bool:
        """True once the outcome is final."""
        return self._future.done()

    @property
    def cancelled(self) -> bool:
        """True after :meth:`cancel` (the outcome may still be pending)."""
        return self._cancelled

    async def wait(self) -> R:
        """Await the result; raises ``ActionPreempted``/``ActionCancelled``/``ActionFailed``."""
        return await self._future

    def __await__(self) -> Any:
        return self._future.__await__()

    def cancel(self, reason: str = "") -> None:
        """Cancel the action. Idempotent."""
        if self._future.done() or self._cancelled:
            return
        self._cancelled = True
        self._cancel_reason = reason
        task = self.task
        if task is not None and not task.done():
            task.cancel()

    def _resolve(self, value: R) -> None:
        if not self._future.done():
            self._future.set_result(value)

    def _reject(self, error: BaseException) -> None:
        if not self._future.done():
            self._future.set_exception(error)

    def __repr__(self) -> str:
        return (
            f"ActionHandle(action={self.action.name!r}, priority={self.priority.name}, "
            f"state={self.state.value})"
        )
