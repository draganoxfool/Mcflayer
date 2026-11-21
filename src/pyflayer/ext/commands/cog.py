"""Cogs: groups of commands, listeners and loops.

A :class:`Cog` subclass is a unit the bot can add, remove and reload as one object. ``CogMeta``
collects the commands, listeners and loops declared on the class so the bot can register them in one
pass.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, ClassVar

from pyflayer.events.catalog import event_for_name
from pyflayer.ext.commands.core import Command

__all__ = ["Cog", "CogMeta", "listener"]


def listener(name: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a method as an event listener.

    Args:
        name: Optional event handler name (``on_chat``). Defaults to the method name.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__cog_listener__ = name or func.__name__
        return func

    return decorator


class CogMeta(type):
    """Collects ``Command``, ``Loop`` and listener declarations from a class body."""

    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> Any:
        from pyflayer.ext.tasks.loop import Loop

        commands: dict[str, Command] = {}
        listeners: list[tuple[str, Callable[..., Any]]] = []
        loops: list[tuple[str, Loop]] = []
        for base in reversed(bases):
            for existing in getattr(base, "__cog_commands__", ()):
                commands[existing.name] = existing
            listeners.extend(getattr(base, "__cog_listeners__", ()))
            loops.extend(getattr(base, "__cog_loops__", ()))
        for attr, value in namespace.items():
            if isinstance(value, Command):
                value.name = value.name or attr
                commands[value.name] = value
            elif isinstance(value, Loop):
                loops.append((attr, value))
            elif callable(value) and hasattr(value, "__cog_listener__"):
                listeners.append((value.__cog_listener__, value))
        cls = super().__new__(mcls, name, bases, namespace)
        cls.__cog_commands__ = list(commands.values())
        cls.__cog_listeners__ = listeners
        cls.__cog_loops__ = loops
        return cls


def _bind_hook(hook: Any, instance: Any) -> Any:
    """Bind a class-body hook to its cog instance, leaving free functions untouched."""
    if hook is not None and inspect.isfunction(hook):
        params = list(inspect.signature(hook).parameters.values())
        if params and params[0].name in ("self", "cls"):
            return hook.__get__(instance, type(instance))
    return hook


class Cog(metaclass=CogMeta):
    """Base class for a group of commands, listeners and loops."""

    __cog_commands__: ClassVar[list[Command]]
    __cog_listeners__: ClassVar[list[tuple[str, Callable[..., Any]]]]
    __cog_loops__: ClassVar[list[tuple[str, Any]]]

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def listener(name: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Declare an event listener method."""
        return listener(name)

    def get_commands(self) -> list[Command]:
        """Commands declared on this cog, with ``cog`` set to this instance."""
        for command in self.__cog_commands__:
            command.cog = self
            # Decorators such as ``@command.error`` run in the class body, so their callbacks
            # are still unbound functions. Bind them like ordinary methods before use.
            command._error = _bind_hook(command._error, self)
            command._before = _bind_hook(command._before, self)
            command._after = _bind_hook(command._after, self)
        return list(self.__cog_commands__)

    def get_listeners(self) -> list[tuple[str, Callable[..., Any]]]:
        """Event handler names and bound listener callables."""
        return [(name, getattr(self, func.__name__)) for name, func in self.__cog_listeners__]

    def get_loops(self) -> list[Any]:
        """Loop instances declared on this cog, bound to this instance."""
        loops = []
        for attr, _loop in self.__cog_loops__:
            loops.append(getattr(self, attr))
        return loops

    @property
    def qualified_name(self) -> str:
        """Lower-case class name used by the bot's cog registry."""
        return type(self).__name__.lower()

    async def cog_load(self) -> None:
        """Called after the cog is added."""

    async def cog_unload(self) -> None:
        """Called before the cog is removed."""

    async def cog_check(self, ctx: Any) -> bool:
        """A check applied to every command of this cog."""
        return True

    async def cog_before_invoke(self, ctx: Any) -> None:
        """Hook run before a cog command."""

    async def cog_after_invoke(self, ctx: Any) -> None:
        """Hook run after a cog command."""

    async def cog_command_error(self, ctx: Any, error: BaseException) -> None:
        """Handle an error raised by a command of this cog.

        The default implementation re-raises so the command-level ``Command.error`` handler and
        the bot-wide fallback still run. Override it without re-raising to suppress an error.
        """
        raise error

    def __repr__(self) -> str:
        return f"<Cog {type(self).__name__}>"


def _listener_event(name: str) -> type:
    """Resolve a listener handler name to its event class."""
    return event_for_name(name)
