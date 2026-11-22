"""Follow a planned path with per-tick controls.

The executor writes only through the action lease it is handed, so a higher-priority action can
preempt movement at any time. Progress is checked against the next waypoint; a bot that stops moving
(fence, unloaded chunk, server setback) raises ``ActionFailed`` after ``stuck_ticks``.

Examples:
    >>> executor = PathExecutor(bot)
    >>> await executor.follow(path, lease)
"""

from __future__ import annotations

import contextlib
import math
from typing import Any, Protocol

from pyflayer.errors import ActionFailed
from pyflayer.events.catalog import (
    GoalReachedEvent,
    PathResetEvent,
    PathUpdatedEvent,
    PhysicsTickEvent,
)
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.pathfinder.planner import Path

__all__ = ["PathExecutor"]


class ExecutorHost(Protocol):
    """Host surface required by :class:`PathExecutor`."""

    position: Vec3 | None
    events: Any

    def look(self, *, yaw: float | None = None, pitch: float | None = None) -> None: ...


class PathExecutor:
    """Turns waypoints into movement input.

    Args:
        host: Bot-like object with ``position``, ``events`` and ``look``.
        reach: Horizontal tolerance at a waypoint, in blocks.
        stuck_ticks: Consecutive ticks without progress before failing.
        max_ticks_per_node: Hard cap per waypoint (protects against oscillation).
    """

    __slots__ = ("host", "max_ticks_per_node", "reach", "stuck_ticks")

    def __init__(
        self,
        host: ExecutorHost,
        *,
        reach: float = 0.28,
        stuck_ticks: int = 60,
        max_ticks_per_node: int = 240,
    ) -> None:
        self.host = host
        self.reach = reach
        self.stuck_ticks = stuck_ticks
        self.max_ticks_per_node = max_ticks_per_node

    async def follow(self, path: Path, lease: Any) -> None:
        """Walk every waypoint after the first; stop controls on completion."""
        try:
            for node in path.points[1:]:
                await self._step(node, lease)
                self.host.events.dispatch(
                    PathUpdatedEvent(
                        position=self.host.position, waypoint=node
                    )
                )
        except Exception as exc:
            with contextlib.suppress(Exception):
                self.host.events.dispatch(PathResetEvent(reason=str(exc)))
            raise
        finally:
            lease.controls.stop()
        with contextlib.suppress(Exception):
            self.host.events.dispatch(GoalReachedEvent(goal=path.end))

    async def _step(self, node: BlockPos, lease: Any) -> None:
        ticks = 0
        stalled = 0
        last: Vec3 | None = self.host.position
        while True:
            position = self.host.position
            if position is None:
                raise ActionFailed("cannot follow a path without a position")
            dx = node.x + 0.5 - position.x
            dz = node.z + 0.5 - position.z
            dy = node.y - position.y
            if abs(dx) <= self.reach and abs(dz) <= self.reach and -0.55 <= dy <= 1.05:
                lease.controls.stop()
                return
            if ticks >= self.max_ticks_per_node:
                raise ActionFailed(
                    "waypoint not reached", target=node, position=position, ticks=ticks
                )
            if last is not None and position.distance_to(last) < 0.005:
                stalled += 1
            else:
                stalled = 0
            if stalled >= self.stuck_ticks:
                raise ActionFailed("path executor stuck", target=node, position=position)
            last = position

            yaw = math.degrees(math.atan2(-dx, dz))
            distance = math.hypot(dx, dz)
            lease.look(yaw, 0.0)
            lease.controls.set(
                forward=1.0 if distance > self.reach else 0.0,
                strafe=0.0,
                sprint=distance > 3.0,
                sneak=False,
            )
            if dy > 0.2:
                lease.jump()
            ticks += 1
            await self.host.events.wait_for(PhysicsTickEvent, timeout=1.0)
