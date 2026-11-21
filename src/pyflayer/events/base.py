"""Event base class and handler-name derivation.

Examples:
    >>> from pyflayer.events.catalog import ChatEvent
    >>> ChatEvent.__event_name__
    'on_chat'
"""

from __future__ import annotations

import re
from typing import ClassVar

__all__ = ["Event", "event_name"]

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


class Event:
    """Base class for every bus event.

    Subclasses are frozen dataclasses (or at least immutable value objects). The bus dispatches on
    the concrete class, so there is no string lookup on the hot path.
    """

    __event_name__: ClassVar[str] = "on_event"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__event_name__" not in cls.__dict__:
            cls.__event_name__ = event_name(cls.__name__)

    @classmethod
    def handler_name(cls) -> str:
        """The ``on_*`` name used by ``bot.event`` and cog listeners."""
        return cls.__event_name__


def event_name(class_name: str) -> str:
    """Derive a bus handler name from an event class name.

    ``ChatEvent`` becomes ``on_chat``; ``PlayerInfoEvent`` becomes ``on_player_info``.
    """
    stem = class_name
    if stem.endswith("Event"):
        stem = stem[:-5]
    snake = _CAMEL_BOUNDARY.sub("_", stem).lower()
    return f"on_{snake}"
