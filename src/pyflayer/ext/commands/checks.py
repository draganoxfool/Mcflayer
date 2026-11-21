"""Checks, cooldowns and concurrency limits.

Checks are predicates over :class:`~pyflayer.ext.commands.context.Context`. They are attached to a
command with the :func:`check` decorator and run before the command body. ``cooldown`` and
``max_concurrency`` use a :class:`BucketType` to decide whether the limit is global, per-player, or
per-channel (there are no channels in Minecraft, so ``default`` behaves like ``global_``).
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pyflayer.ext.commands.errors import (
    CheckFailure,
    CommandOnCooldown,
    MaxConcurrencyReached,
    NotOwner,
)

__all__ = [
    "BucketType",
    "Check",
    "Cooldown",
    "CooldownMapping",
    "check",
    "check_any",
    "cooldown",
    "has_player_nearby",
    "in_dimension",
    "is_owner",
    "max_concurrency",
]


class BucketType(Enum):
    """How a rate limit is keyed."""

    default = 0
    player = 1
    global_ = 2


Check = Callable[[Any], bool | Awaitable[bool]]


def check(predicate: Check) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach a check to a command callback."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        checks = getattr(func, "__commands_checks__", None)
        if checks is None:
            checks = []
            func.__commands_checks__ = checks
        checks.append(predicate)
        return func

    return decorator


def check_any(*predicates: Check) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Pass when at least one predicate passes."""

    async def combined(ctx: Any) -> bool:
        errors: list[BaseException] = []
        for predicate in predicates:
            try:
                result = predicate(ctx)
                if inspect.isawaitable(result):
                    result = await result
                if result:
                    return True
            except CheckFailure as exc:
                errors.append(exc)
        raise CheckFailure(f"none of the checks passed: {errors!r}")

    return check(combined)


def is_owner() -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Only allow configured bot owners."""

    async def predicate(ctx: Any) -> bool:
        owner_ids = getattr(ctx.bot, "owner_ids", ())
        if not owner_ids:
            return True
        return ctx.author in owner_ids or ctx.sender_name in owner_ids

    return check(predicate)


def in_dimension(*dimensions: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Only allow the command in one of the given dimension ids."""

    async def predicate(ctx: Any) -> bool:
        return ctx.bot.dimension in dimensions

    return check(predicate)


def has_player_nearby(distance: float) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Only allow when a tracked player is within ``distance`` blocks."""

    async def predicate(ctx: Any) -> bool:
        position = getattr(ctx.bot, "position", None)
        if position is None:
            return False
        for entity in ctx.bot.entities.all():
            if not entity.is_player:
                continue
            if position.distance_to(entity.position) <= distance:
                return True
        return False

    return check(predicate)


class _Bucket:
    __slots__ = ("tokens", "window_start")

    def __init__(self) -> None:
        self.tokens = 0
        self.window_start = 0.0


class Cooldown:
    """A token-bucket cooldown definition."""

    __slots__ = ("per", "rate")

    def __init__(self, rate: int, per: float) -> None:
        self.rate = max(1, rate)
        self.per = max(0.0, per)

    def __repr__(self) -> str:
        return f"Cooldown(rate={self.rate}, per={self.per})"


class CooldownMapping:
    """Per-bucket cooldown state, using an injected clock."""

    __slots__ = ("_buckets", "_clock", "cooldown", "type")

    def __init__(
        self, cooldown: Cooldown, type: BucketType = BucketType.default, clock: Any = None
    ) -> None:
        self.cooldown = cooldown
        self.type = type
        self._buckets: dict[str, _Bucket] = {}
        self._clock = clock

    @classmethod
    def from_cooldown(
        cls, rate: int, per: float, type: BucketType = BucketType.default, clock: Any = None
    ) -> CooldownMapping:
        return cls(Cooldown(rate, per), type, clock)

    def _key(self, ctx: Any) -> str:
        if self.type is BucketType.player:
            return f"player:{ctx.sender_name}"
        return "global"

    def update(self, ctx: Any) -> float | None:
        """Consume a token; return the retry-after seconds when limited, else ``None``."""
        if self.cooldown.per <= 0:
            return None
        now = self._clock() if self._clock is not None else time.monotonic()
        bucket = self._buckets.get(self._key(ctx))
        if bucket is None:
            bucket = _Bucket()
            bucket.window_start = now
            self._buckets[self._key(ctx)] = bucket
        if now - bucket.window_start >= self.cooldown.per:
            bucket.window_start = now
            bucket.tokens = 0
        if bucket.tokens >= self.cooldown.rate:
            return max(0.0, bucket.window_start + self.cooldown.per - now)
        bucket.tokens += 1
        return None

    def reset(self) -> None:
        self._buckets.clear()


def cooldown(
    rate: int,
    per: float,
    type: BucketType = BucketType.default,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Apply a cooldown to a command."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        mapping = CooldownMapping.from_cooldown(rate, per, type)
        func.__commands_cooldown__ = mapping
        return func

    return decorator


def max_concurrency(
    number: int,
    per: BucketType = BucketType.default,
    *,
    wait: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Limit how many invocations of a command may run at once."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__commands_max_concurrency__ = number, per, wait
        return func

    return decorator


__all__ += ["CheckFailure", "CommandOnCooldown", "MaxConcurrencyReached", "NotOwner"]
