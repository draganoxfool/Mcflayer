"""Always-on survival monitor: eat when health is low and food allows it.

The monitor only reacts to :class:`~pyflayer.events.catalog.HealthEvent`; eating is submitted at
``Priority.SURVIVAL`` so work actions yield automatically.

Examples:
    >>> monitor = SurvivalMonitor(bot, threshold=6.0)
    >>> monitor.start()
"""

from __future__ import annotations

from typing import Any

from pyflayer.actions.base import Priority
from pyflayer.actions.basic import Eat
from pyflayer.errors import ActionError
from pyflayer.events.catalog import HealthEvent

__all__ = ["SurvivalMonitor"]


class SurvivalMonitor:
    """Low-health eating policy.

    Args:
        host: Bot-like object with ``events``, ``scheduler`` and ``inventory``.
        threshold: Health at or below which the bot should eat.
        max_food: Stop eating once food reaches this value.
    """

    __slots__ = ("_subscription", "enabled", "food", "health", "host", "max_food", "threshold")

    def __init__(
        self,
        host: Any,
        *,
        threshold: float = 6.0,
        max_food: int = 20,
    ) -> None:
        self.host = host
        self.threshold = threshold
        self.max_food = max_food
        self.enabled = True
        self.health = 20.0
        self.food = 20
        self._subscription: Any = None

    def start(self) -> None:
        """Subscribe to health updates (idempotent)."""
        if self._subscription is not None:
            return
        self._subscription = self.host.events.subscribe(HealthEvent, self._on_health)

    def stop(self) -> None:
        """Unsubscribe."""
        if self._subscription is not None:
            self.host.events.unsubscribe(self._subscription)
            self._subscription = None

    def _on_health(self, event: HealthEvent) -> None:
        self.health = event.health
        self.food = event.food
        if not self.enabled or event.health <= 0:
            return
        if event.health > self.threshold or event.food <= 0 or event.food >= self.max_food:
            return
        current = self.host.scheduler.current()
        if current is not None and current.action.name == "eat":
            return
        handle = self.host.scheduler.run(Eat(), priority=Priority.SURVIVAL)
        handle.task.add_done_callback(self._swallow_errors)

    @staticmethod
    def _swallow_errors(task: Any) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if isinstance(error, ActionError):
            return
        if error is not None:
            raise error
