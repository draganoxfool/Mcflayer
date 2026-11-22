"""Argument converters.

A converter turns one textual argument into a typed Python value. Built-ins cover the common
Minecraft shapes; ``Greedy`` and ``Range`` mirror the discord.py convenience helpers. Resolution is
explicit ``Annotated``/``Converter`` first, then the built-in map, then ``Literal``/enums, then a
callable annotation.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Protocol, TypeVar, get_args, get_origin

from pyflayer.ext.commands.errors import BadArgument, BadUnionArgument, ConversionError
from pyflayer.models.enums import Dimension, GameMode

__all__ = [
    "Converter",
    "ConverterT",
    "Greedy",
    "IdentityConverter",
    "Range",
    "convert",
    "resolve_converter",
]

T_co = TypeVar("T_co", covariant=True)
ConverterT = TypeVar("ConverterT")
_MISSING = object()


class Converter(Protocol[T_co]):
    """Structural protocol for a converter."""

    async def convert(self, ctx: Any, argument: str) -> T_co: ...


class _GreedyAnnotation:
    """Marker returned by ``Greedy[T]`` at annotation-evaluation time."""

    __slots__ = ("item",)

    def __init__(self, item: object) -> None:
        self.item = item

    def __repr__(self) -> str:
        return f"Greedy[{self.item!r}]"


class Greedy:
    """Consume the remaining tokens and convert each one.

    ``Greedy[str]`` yields ``list[str]``; ``Greedy[int]`` yields ``list[int]``.
    """

    def __class_getitem__(cls, item: object) -> _GreedyAnnotation:
        return _GreedyAnnotation(item)


class _RangeAnnotation:
    """Marker returned by ``Range[T, lo, hi]`` at annotation-evaluation time."""

    __slots__ = ("base", "maximum", "minimum")

    def __init__(self, base: object, minimum: object, maximum: object) -> None:
        self.base = base
        self.minimum = minimum
        self.maximum = maximum

    def __repr__(self) -> str:
        return f"Range[{self.base!r}, {self.minimum!r}, {self.maximum!r}]"


class Range:
    """Bounded numeric argument, e.g. ``commands.Range[int, 1, 64]``.

    ``None`` for either bound means unbounded on that side.
    """

    def __class_getitem__(cls, params: object) -> _RangeAnnotation:
        if not isinstance(params, tuple) or len(params) != 3:
            raise TypeError("Range expects Range[type, minimum, maximum]")
        return _RangeAnnotation(params[0], params[1], params[2])


class IdentityConverter:
    """Return the argument unchanged (``str``)."""

    async def convert(self, ctx: Any, argument: str) -> str:
        del ctx
        return argument


class _IntConverter:
    async def convert(self, ctx: Any, argument: str) -> int:
        del ctx
        try:
            return int(argument, 10)
        except ValueError:
            raise BadArgument(None, argument, "expected an integer") from None


class _FloatConverter:
    async def convert(self, ctx: Any, argument: str) -> float:
        del ctx
        try:
            return float(argument)
        except ValueError:
            raise BadArgument(None, argument, "expected a number") from None


class _BoolConverter:
    _TRUE = frozenset({"1", "true", "yes", "on", "y"})
    _FALSE = frozenset({"0", "false", "no", "off", "n"})

    async def convert(self, ctx: Any, argument: str) -> bool:
        del ctx
        lowered = argument.lower()
        if lowered in self._TRUE:
            return True
        if lowered in self._FALSE:
            return False
        raise BadArgument(None, argument, "expected a boolean")


class _EnumConverter:
    def __init__(self, enum: Any) -> None:
        self.enum = enum

    async def convert(self, ctx: Any, argument: str) -> Any:
        del ctx
        for member in self.enum:
            if (
                member.name.lower() == argument.lower()
                or str(member.value).lower() == argument.lower()
            ):
                return member
        raise BadArgument(
            None, argument, f"expected one of {', '.join(m.name.lower() for m in self.enum)}"
        )


class _LiteralConverter:
    def __init__(self, values: tuple[Any, ...]) -> None:
        self.values = values

    async def convert(self, ctx: Any, argument: str) -> Any:
        del ctx
        for value in self.values:
            if str(value) == argument or (
                isinstance(value, str) and value.lower() == argument.lower()
            ):
                return value
        raise BadArgument(None, argument, f"expected one of {', '.join(map(str, self.values))}")


class _CallableConverter:
    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func

    async def convert(self, ctx: Any, argument: str) -> Any:
        del ctx
        result = self.func(argument)
        if isinstance(result, Awaitable):
            result = await result
        return result


class _UnionConverter:
    def __init__(self, converters: list[Any]) -> None:
        self.converters = converters

    async def convert(self, ctx: Any, argument: str) -> Any:
        errors: list[BaseException] = []
        for converter in self.converters:
            try:
                return await _apply(converter, ctx, argument)
            except Exception as exc:
                errors.append(exc)
        raise BadUnionArgument(None, argument, errors)


class _RangeConverter:
    def __init__(self, base: Any, minimum: Any, maximum: Any) -> None:
        self.base = base
        self.minimum = minimum
        self.maximum = maximum

    async def convert(self, ctx: Any, argument: str) -> Any:
        value = await _apply(self.base, ctx, argument)
        try:
            if self.minimum is not None and value < self.minimum:
                raise BadArgument(None, argument, f"must be at least {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise BadArgument(None, argument, f"must be at most {self.maximum}")
        except TypeError:
            raise BadArgument(None, argument, "value is not comparable") from None
        return value


class _Player:
    """Resolve a player name through the bot's tab list."""

    async def convert(self, ctx: Any, argument: str) -> Any:
        getter = getattr(ctx.bot, "get_player", None)
        player = getter(argument) if callable(getter) else None
        if player is None:
            raise BadArgument(None, argument, f"no player named {argument!r}")
        return player


_BUILTINS: dict[Any, Any] = {
    str: IdentityConverter(),
    int: _IntConverter(),
    float: _FloatConverter(),
    bool: _BoolConverter(),
    Dimension: _EnumConverter(Dimension),
    GameMode: _EnumConverter(GameMode),
}


class _PlayerAnnotation:
    """Marker used as ``Player`` in command signatures."""

    def __repr__(self) -> str:
        return "Player"


Player = _PlayerAnnotation()
_BUILTINS[_PlayerAnnotation] = _Player()


async def _apply(converter: Any, ctx: Any, argument: str) -> Any:
    if converter is None:
        return argument
    method = getattr(converter, "convert", None)
    if method is not None:
        try:
            return await method(ctx, argument)
        except (BadArgument, BadUnionArgument):
            raise
        except Exception as exc:
            raise ConversionError(None, exc) from exc
    if isinstance(converter, type):
        try:
            return converter(argument)
        except Exception as exc:
            raise BadArgument(None, argument, f"could not convert to {converter.__name__}") from exc
    if callable(converter):
        result = converter(argument)
        if isinstance(result, Awaitable):
            result = await result
        return result
    return argument


def _as_converter(annotation: object) -> Any:
    """Resolve an annotation to a converter object (or ``None`` for identity)."""
    if annotation is inspect_empty or annotation is _MISSING:
        return None
    # Unhashable markers must be handled before the dict lookup.
    if isinstance(annotation, _GreedyAnnotation):
        return _as_converter(annotation.item)
    if isinstance(annotation, _RangeAnnotation):
        return _RangeConverter(
            _as_converter(annotation.base), annotation.minimum, annotation.maximum
        )
    if isinstance(annotation, _PlayerAnnotation):
        return _BUILTINS[_PlayerAnnotation]
    if annotation is str:
        return IdentityConverter()
    if isinstance(annotation, type) and annotation in _BUILTINS:
        return _BUILTINS[annotation]
    origin = get_origin(annotation)
    if origin is typing.Annotated:
        args = get_args(annotation)
        # An explicit converter in the metadata wins over the base annotation.
        for metadata in args[1:]:
            if isinstance(metadata, _PlayerAnnotation):
                return _BUILTINS[_PlayerAnnotation]
            if hasattr(metadata, "convert"):
                return metadata
            if isinstance(metadata, type) and hasattr(metadata, "convert"):
                return metadata()
        return _as_converter(args[0])
    if origin is typing.Literal:
        return _LiteralConverter(get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
        if len(args) == 1:
            return _as_converter(args[0])
        return _UnionConverter([_as_converter(arg) for arg in args])
    if isinstance(annotation, type) and hasattr(annotation, "convert"):
        return annotation()
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return _EnumConverter(annotation)
    if isinstance(annotation, type):
        return annotation
    if callable(annotation):
        return _CallableConverter(annotation)
    return None


def resolve_converter(annotation: object) -> Any:
    """Public wrapper around :func:`_as_converter`."""
    return _as_converter(annotation)


async def convert(ctx: Any, converter: Any, argument: str) -> Any:
    """Apply ``converter`` to ``argument``."""
    return await _apply(converter, ctx, argument)


inspect_empty = inspect.Parameter.empty
