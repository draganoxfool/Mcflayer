"""Ergonomic action API attached to the bot (``bot.actions``).

Examples:
    >>> await bot.actions.goto(BlockPos(12, 64, -4))
    >>> await bot.actions.dig(BlockPos(12, 63, -4))
    >>> await bot.actions.attack()
"""

from __future__ import annotations

from typing import Any, cast

from pyflayer.actions.base import Action, ActionHandle, Priority, Resource
from pyflayer.actions.basic import (
    Attack,
    Dig,
    Eat,
    Equip,
    GoTo,
    Look,
    LookAt,
    Place,
)
from pyflayer.actions.scheduler import ActionScheduler
from pyflayer.models.enums import Face
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.pathfinder.goals import Goal
from pyflayer.world.entities import Entity

__all__ = ["ActionFacade"]


class ActionFacade:
    """Thin, typed front door to the scheduler and built-in actions."""

    __slots__ = ("host",)

    def __init__(self, host: Any) -> None:
        self.host = host

    @property
    def scheduler(self) -> ActionScheduler:
        """The bot's scheduler."""
        return cast(ActionScheduler, self.host.scheduler)

    def run(
        self,
        action: Action[Any],
        *,
        priority: Priority = Priority.WORK,
        preempt: bool = True,
        queue: bool = False,
        timeout: float | None = None,
    ) -> ActionHandle[Any]:
        """Submit an arbitrary action."""
        return self.scheduler.run(
            action, priority=priority, preempt=preempt, queue=queue, timeout=timeout
        )

    def look(self, yaw: float, pitch: float = 0.0, **kwargs: Any) -> ActionHandle[None]:
        """Set the look direction."""
        return self.run(Look(yaw, pitch), **kwargs)

    def look_at(
        self, target: BlockPos | Vec3 | Entity, **kwargs: Any
    ) -> ActionHandle[None]:
        """Look at a block, vector or entity."""
        return self.run(LookAt(target), **kwargs)

    def goto(
        self, goal: Goal | BlockPos | Vec3, **kwargs: Any
    ) -> ActionHandle[Any]:
        """Plan and walk to ``goal`` (accepts a ``BlockPos`` for convenience)."""
        priority = kwargs.pop("priority", Priority.WORK)
        allow_partial = kwargs.pop("allow_partial", False)
        max_nodes = kwargs.pop("max_nodes", 5000)
        return self.run(
            GoTo(goal, allow_partial=allow_partial, max_nodes=max_nodes),
            priority=priority,
            **kwargs,
        )

    def dig(self, pos: BlockPos, **kwargs: Any) -> ActionHandle[bool]:
        """Break a block."""
        return self.run(Dig(pos), **kwargs)

    def place(
        self, pos: BlockPos, *, face: Face = Face.UP, **kwargs: Any
    ) -> ActionHandle[bool]:
        """Place the held item against ``pos``."""
        return self.run(Place(pos, face=face), **kwargs)

    def equip(self, item: str | int, *, hotbar: int = 0, **kwargs: Any) -> ActionHandle[int]:
        """Equip an item by name or id."""
        return self.run(Equip(item, hotbar=hotbar), **kwargs)

    def eat(self, **kwargs: Any) -> ActionHandle[str | None]:
        """Eat hotbar food (survival priority by default)."""
        kwargs.setdefault("priority", Priority.SURVIVAL)
        return self.run(Eat(), **kwargs)

    def attack(
        self, target: Entity | int | None = None, *, reach: float = 3.5, **kwargs: Any
    ) -> ActionHandle[Entity]:
        """Attack an entity or the nearest one."""
        kwargs.setdefault("priority", Priority.COMBAT)
        return self.run(Attack(target, reach=reach), **kwargs)

    def stop(self) -> None:
        """Cancel everything below emergency priority."""
        self.scheduler.cancel_all(reason="stopped by user")

    def __repr__(self) -> str:
        return f"ActionFacade(active={len(self.scheduler.active)})"


__all__ += ["Resource"]
