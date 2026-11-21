"""Command and group objects plus their decorators.

A :class:`Command` wraps an ``async def name(self, ctx, ...)`` callable whose signature is parsed
into typed parameters. The first parameter after ``ctx`` may be positional, keyword-only or a
``*args`` varargs tuple; each is converted with :mod:`pyflayer.ext.commands.converters`.
"""

from __future__ import annotations

import asyncio
import inspect
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pyflayer.ext.commands.converters import (
    _GreedyAnnotation,
    convert as convert_argument,
    resolve_converter,
)
from pyflayer.ext.commands.errors import (
    CheckFailure,
    CommandInvokeError,
    CommandOnCooldown,
    MissingRequiredArgument,
    TooManyArguments,
)
from pyflayer.ext.commands.flags import FlagConverter
from pyflayer.ext.commands.view import StringView

__all__ = ["Command", "Group", "Parameter", "command", "group"]

_MISSING = inspect.Parameter.empty


@dataclass(slots=True)
class Parameter:
    """One parsed command parameter."""

    name: str
    kind: inspect._ParameterKind
    default: Any = _MISSING
    annotation: Any = _MISSING
    converter: Any = None
    greedy: bool = False
    flags: bool = False

    @property
    def required(self) -> bool:
        return self.default is _MISSING


def _parse_parameters(func: Callable[..., Any]) -> list[Parameter]:
    signature = inspect.signature(func)
    params = list(signature.parameters.values())
    try:
        # ``include_extras`` keeps Annotated metadata available for converter resolution.
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001 - fall back to raw annotations
        hints = {}
    index = 0
    if params and params[0].name in ("self", "cls"):
        index = 1
    if index < len(params) and params[index].name == "ctx":
        index += 1
    result: list[Parameter] = []
    for param in params[index:]:
        annotation = hints.get(param.name, param.annotation)
        greedy = isinstance(annotation, _GreedyAnnotation)
        flags = isinstance(annotation, type) and issubclass(annotation, FlagConverter)
        converter = resolve_converter(annotation)
        result.append(
            Parameter(
                name=param.name,
                kind=param.kind,
                default=param.default,
                annotation=annotation,
                converter=converter,
                greedy=greedy,
                flags=flags,
            )
        )
    return result


class Command:
    """A single chat command."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        aliases: Sequence[str] = (),
        brief: str | None = None,
        description: str | None = None,
        hidden: bool = False,
        enabled: bool = True,
        parent: Group | None = None,
    ) -> None:
        self.callback = func
        self.name = name or func.__name__
        self.aliases = tuple(aliases)
        self.brief = brief
        self.description = description or inspect.getdoc(func)
        self.hidden = hidden
        self.enabled = enabled
        self.parent = parent
        self.cog: Any = None
        self.params = _parse_parameters(func)
        self.checks: list[Callable[..., Any]] = list(getattr(func, "__commands_checks__", []))
        self.cooldown = getattr(func, "__commands_cooldown__", None)
        self.max_concurrency = getattr(func, "__commands_max_concurrency__", None)
        self._error: Callable[..., Any] | None = None
        self._before: Callable[..., Any] | None = None
        self._after: Callable[..., Any] | None = None
        self._running: dict[str, int] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    # ------------------------------------------------------------------ decorators
    def error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register a per-command error handler."""
        self._error = coro
        return coro

    def before_invoke(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook awaited before the body."""
        self._before = coro
        return coro

    def after_invoke(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook awaited after the body."""
        self._after = coro
        return coro

    # ------------------------------------------------------------------ parsing
    async def prepare(self, ctx: Any) -> None:
        """Parse and convert arguments, then run checks and cooldowns."""
        for param in self.params:
            await self._consume(ctx, param)
        if not ctx.view.eof and ctx.view.read():
            raise TooManyArguments(f"too many arguments for {self.name!r}")

        await self.can_run(ctx)

        if self.cooldown is not None:
            if self.cooldown._clock is None:
                self.cooldown._clock = ctx.bot.clock.monotonic
            retry = self.cooldown.update(ctx)
            if retry is not None:
                raise CommandOnCooldown(retry)

    async def _consume(self, ctx: Any, param: Parameter) -> None:
        view: StringView = ctx.view
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            values = []
            while True:
                token = view.get_quoted_word()
                if token is None:
                    break
                values.append(await convert_argument(ctx, param.converter, token))
            ctx.args.append(values)
            return
        if param.flags:
            rest = view.read_rest().strip()
            instance = param.annotation()
            ctx.args.append(await instance.convert(ctx, rest))
            return
        if param.greedy:
            values = []
            while True:
                token = view.get_quoted_word()
                if token is None:
                    break
                values.append(await convert_argument(ctx, param.converter, token))
            ctx.args.append(values)
            return
        token = view.get_quoted_word()
        if token is None:
            if param.required:
                raise MissingRequiredArgument(param)
            return
        value = await convert_argument(ctx, param.converter, token)
        if param.kind is inspect.Parameter.KEYWORD_ONLY:
            ctx.kwargs[param.name] = value
        else:
            ctx.args.append(value)

    # ------------------------------------------------------------------ checks
    async def can_run(self, ctx: Any) -> bool:
        """Run command, cog and concurrency checks.

        Raises:
            CheckFailure: When a check fails, a cooldown applies or concurrency is exceeded.
        """
        for predicate in self.checks:
            result = predicate(ctx)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                raise CheckFailure(f"check {getattr(predicate, '__name__', predicate)!r} failed")
        cog = self.cog
        if cog is not None:
            cog_check = getattr(cog, "cog_check", None)
            if cog_check is not None:
                result = cog_check(ctx)
                if inspect.isawaitable(result):
                    result = await result
                if not result:
                    raise CheckFailure(f"cog check for {type(cog).__name__!r} failed")
        if self.max_concurrency is not None:
            number, per, wait = self.max_concurrency
            key = ctx.sender_name if per.name == "player" else "global"
            running = self._running.get(key, 0)
            if running >= number and not wait:
                from pyflayer.ext.commands.errors import MaxConcurrencyReached

                raise MaxConcurrencyReached(number, per)
        return True

    # ------------------------------------------------------------------ invocation
    async def invoke(self, ctx: Any) -> None:
        """Run before hooks, the body and after hooks."""
        if self._before is not None:
            result = self._before(ctx)
            if inspect.isawaitable(result):
                await result
        key = ctx.sender_name if self.max_concurrency and self.max_concurrency[1].name == "player" else "global"
        semaphore: asyncio.Semaphore | None = None
        if self.max_concurrency is not None:
            number, _per, wait = self.max_concurrency
            if wait:
                # A waiting command queues here; the semaphore is released in the finally
                # block below, once the command body has finished.
                semaphore = self._semaphores.get(key)
                if semaphore is None:
                    semaphore = asyncio.Semaphore(number)
                    self._semaphores[key] = semaphore
                await semaphore.acquire()
            else:
                self._running[key] = self._running.get(key, 0) + 1
        try:
            args: list[Any] = [ctx, *ctx.args]
            if self.cog is not None:
                args = [self.cog, *args]
            try:
                result = self.callback(*args, **ctx.kwargs)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - wrapped for the error chain
                raise CommandInvokeError(exc) from exc
        finally:
            if semaphore is not None:
                semaphore.release()
            elif self.max_concurrency is not None:
                self._running[key] = max(0, self._running.get(key, 1) - 1)
        if self._after is not None:
            result = self._after(ctx)
            if inspect.isawaitable(result):
                await result

    @property
    def qualified_name(self) -> str:
        """``group sub`` for subcommands, else the name."""
        if self.parent is not None:
            return f"{self.parent.qualified_name} {self.name}"
        return self.name

    @property
    def short_doc(self) -> str:
        """First line of the description, for help listings."""
        if self.brief:
            return self.brief
        if self.description:
            return self.description.splitlines()[0]
        return ""

    def __repr__(self) -> str:
        return f"<Command {self.qualified_name!r}>"


class Group(Command):
    """A command that can contain subcommands."""

    def __init__(self, *args: Any, invoke_without_command: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.invoke_without_command = invoke_without_command
        self.commands: dict[str, Command] = {}

    def add_command(self, command_obj: Command) -> None:
        """Register a subcommand."""
        command_obj.parent = self
        self.commands[command_obj.name] = command_obj
        for alias in command_obj.aliases:
            self.commands.setdefault(alias, command_obj)

    def get_command(self, name: str) -> Command | None:
        """Look up a subcommand by name or alias."""
        return self.commands.get(name)

    def command(self, **attrs: Any) -> Callable[[Callable[..., Any]], Command]:
        """Decorator that adds a subcommand to this group."""

        def decorator(func: Callable[..., Any]) -> Command:
            created = command(**attrs)(func)
            self.add_command(created)
            return created

        return decorator

    def group(self, **attrs: Any) -> Callable[[Callable[..., Any]], Group]:
        """Decorator that adds a nested group to this group."""

        def decorator(func: Callable[..., Any]) -> Group:
            created = group(**attrs)(func)
            self.add_command(created)
            return created

        return decorator

    def walk_commands(self) -> list[Command]:
        """All subcommands, recursively."""
        result: list[Command] = []
        for command_obj in set(self.commands.values()):
            result.append(command_obj)
            if isinstance(command_obj, Group):
                result.extend(command_obj.walk_commands())
        return result


def command(
    name: str | None = None,
    *,
    aliases: Sequence[str] = (),
    brief: str | None = None,
    description: str | None = None,
    hidden: bool = False,
    enabled: bool = True,
    cls: type[Command] = Command,
    **attrs: Any,
) -> Callable[[Callable[..., Any]], Command]:
    """Turn an ``async def`` into a :class:`Command`."""

    def decorator(func: Callable[..., Any]) -> Command:
        return cls(
            func,
            name=name,
            aliases=aliases,
            brief=brief,
            description=description,
            hidden=hidden,
            enabled=enabled,
            **attrs,
        )

    return decorator


def group(
    name: str | None = None,
    *,
    invoke_without_command: bool = False,
    aliases: Sequence[str] = (),
    brief: str | None = None,
    description: str | None = None,
    hidden: bool = False,
    **attrs: Any,
) -> Callable[[Callable[..., Any]], Group]:
    """Turn an ``async def`` into a :class:`Group`."""

    def decorator(func: Callable[..., Any]) -> Group:
        return Group(
            func,
            name=name,
            aliases=aliases,
            brief=brief,
            description=description,
            hidden=hidden,
            invoke_without_command=invoke_without_command,
            **attrs,
        )

    return decorator
