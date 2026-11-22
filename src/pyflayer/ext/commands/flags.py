"""Keyword-style flags for command arguments.

A :class:`FlagConverter` subclass declares annotated attributes; each may have a default and a
converter. Command arguments of the form ``--name value`` or ``--name=value`` populate them, bare
``--name`` sets a boolean flag to ``True``.

Example:
    >>> class Options(FlagConverter):
    ...     count: int = flag(default=1)
    ...     silent: bool = flag(default=False)
    >>> opts = await Options().convert(ctx, "--count 5 --silent")
    >>> opts.count, opts.silent
    (5, True)
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, ClassVar

from pyflayer.ext.commands.converters import resolve_converter
from pyflayer.ext.commands.errors import BadArgument
from pyflayer.ext.commands.view import tokenize

__all__ = ["Flag", "FlagConverter", "flag", "parse_flags"]


class Flag:
    """A single flag declaration."""

    __slots__ = ("converter", "default", "description")

    def __init__(
        self,
        *,
        default: Any = inspect.Parameter.empty,
        converter: Any = None,
        description: str | None = None,
    ) -> None:
        self.default = default
        self.converter = converter
        self.description = description


def flag(
    *, default: Any = inspect.Parameter.empty, converter: Any = None, description: str | None = None
) -> Flag:
    """Declare a flag on a :class:`FlagConverter` subclass."""
    return Flag(default=default, converter=converter, description=description)


class _FlagMeta(type):
    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> Any:
        cls = super().__new__(mcls, name, bases, namespace)
        flags: dict[str, Flag] = {}
        for base in reversed(cls.__mro__):
            for attr, annotation in getattr(base, "__annotations__", {}).items():
                if attr.startswith("__"):
                    continue
                declaration = getattr(base, attr, None)
                if isinstance(declaration, Flag):
                    flags[attr] = declaration
                elif annotation is not None and attr not in flags:
                    flags[attr] = Flag()
        cls.__command_flags__ = flags
        return cls


class FlagConverter(metaclass=_FlagMeta):
    """Base class for a set of ``--name value`` flags."""

    __command_flags__: ClassVar[dict[str, Flag]] = {}

    def __init__(self) -> None:
        for name in type(self).__command_flags__:
            setattr(self, name, None)

    async def convert(self, ctx: Any, argument: str) -> FlagConverter:
        try:
            hints: dict[str, Any] = typing.get_type_hints(type(self))
        except Exception:
            hints = dict(getattr(type(self), "__annotations__", {}))
        tokens = tokenize(argument)
        values: dict[str, Any] = {}
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if not token.startswith("--"):
                raise BadArgument(None, token, "expected a --flag")
            body = token[2:]
            if "=" in body:
                name, raw = body.split("=", 1)
                index += 1
            else:
                name = body
                if index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
                    raw = tokens[index + 1]
                    index += 2
                else:
                    raw = None
                    index += 1
            declaration = type(self).__command_flags__.get(name)
            if declaration is None:
                raise BadArgument(None, token, f"unknown flag --{name}")
            annotation = hints.get(name)
            if raw is None:
                if annotation is not bool:
                    raise BadArgument(None, token, f"flag --{name} requires a value")
                values[name] = True
                continue
            converter = declaration.converter
            if converter is None:
                converter = resolve_converter(annotation)
            from pyflayer.ext.commands.converters import convert as _convert

            values[name] = await _convert(ctx, converter, raw)
        for name, declaration in type(self).__command_flags__.items():
            if name not in values:
                if declaration.default is inspect.Parameter.empty:
                    raise BadArgument(None, name, f"missing required flag --{name}")
                values[name] = declaration.default
        for name, value in values.items():
            setattr(self, name, value)
        return self

    def __repr__(self) -> str:
        parts = ", ".join(
            f"{name}={getattr(self, name)!r}" for name in type(self).__command_flags__
        )
        return f"{type(self).__name__}({parts})"


def parse_flags(schema: dict[str, Flag], argument: str) -> dict[str, Any]:
    """Parse ``--flag value`` pairs against ``schema`` without a context."""
    tokens = tokenize(argument)
    result: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise BadArgument(None, token, "expected a --flag")
        body = token[2:]
        if "=" in body:
            name, value = body.split("=", 1)
            index += 1
        else:
            name = body
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
                value = tokens[index + 1]
                index += 2
            else:
                value = None
                index += 1
        if name not in schema:
            raise BadArgument(None, token, f"unknown flag --{name}")
        result[name] = True if value is None else value
    return result
