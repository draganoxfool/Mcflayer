"""Command-layer exception tree.

Every error derives from :class:`CommandError`, itself a :class:`~pyflayer.errors.PyFlayerError`
(ADR-10). :class:`CommandPrefixError` additionally derives from :class:`TypeError` so a ported
discord.py snippet that passes ``command_prefix=`` fails loudly at construction time (ADR-11).
"""

from __future__ import annotations

from typing import Any

from pyflayer.errors import PyFlayerError

__all__ = [
    "BadArgument",
    "BadUnionArgument",
    "CheckAnyFailure",
    "CheckFailure",
    "CommandError",
    "CommandInvokeError",
    "CommandNotFound",
    "CommandOnCooldown",
    "CommandPrefixError",
    "ConversionError",
    "DisabledCommand",
    "ExtensionAlreadyLoaded",
    "ExtensionError",
    "ExtensionFailed",
    "ExtensionNotLoaded",
    "MaxConcurrencyReached",
    "MissingRequiredArgument",
    "NotOwner",
    "TooManyArguments",
    "UserInputError",
]


class CommandError(PyFlayerError):
    """Base class for every command-layer error."""


class CommandPrefixError(TypeError, CommandError):
    """Raised when ``command_prefix=`` is passed to :class:`commands.Bot`.

    mcflayer has no command prefix: a message is a command only when it is addressed to the bot
    (whisper or name mention) or dispatched programmatically (ADR-11).
    """

    def __init__(
        self,
        message: str = (
            "command_prefix is not supported: address messages to the bot or use "
            "bot.dispatch_command()"
        ),
    ) -> None:
        CommandError.__init__(self, message)


class CommandNotFound(CommandError):
    """No command matched the invoked name."""

    def __init__(self, name: str, **fields: Any) -> None:
        super().__init__(f"command {name!r} not found", name=name, **fields)
        self.name = name


class DisabledCommand(CommandError):
    """The resolved command is disabled and cannot be invoked."""


class UserInputError(CommandError):
    """The caller supplied arguments that could not be used."""

    def __init__(
        self, message: str = "invalid input", *, param: object = None, **fields: Any
    ) -> None:
        super().__init__(message, param=param, **fields)
        self.param = param


class MissingRequiredArgument(UserInputError):
    """A required parameter was not supplied."""

    def __init__(self, param: object = None, **fields: Any) -> None:
        name = getattr(param, "name", param)
        super().__init__(f"missing required argument {name!r}", param=param, **fields)
        self.name = name


class BadArgument(UserInputError):
    """A converter rejected an argument."""

    def __init__(self, param: object, argument: str, reason: str, **fields: Any) -> None:
        name = getattr(param, "name", param)
        super().__init__(
            f"bad argument for {name!r}: {reason}",
            param=param,
            argument=argument,
            reason=reason,
            **fields,
        )
        self.argument = argument
        self.reason = reason


class TooManyArguments(UserInputError):
    """More positional arguments were supplied than the command accepts."""


class BadUnionArgument(UserInputError):
    """No member of a ``Union`` converter accepted the argument."""

    def __init__(
        self, param: object, argument: str, errors: list[BaseException] | None = None, **fields: Any
    ) -> None:
        name = getattr(param, "name", param)
        super().__init__(
            f"could not convert {argument!r} for {name!r}",
            param=param,
            argument=argument,
            errors=errors or [],
            **fields,
        )
        self.argument = argument
        self.errors = errors or []


class ConversionError(UserInputError):
    """An unexpected exception escaped a converter."""

    def __init__(self, param: object, original: BaseException | None = None, **fields: Any) -> None:
        super().__init__(
            f"converter for {getattr(param, 'name', param)!r} raised {original!r}",
            param=param,
            original=original,
            **fields,
        )
        self.original = original


class CheckFailure(CommandError):
    """A check predicate returned ``False``."""


class NotOwner(CheckFailure):
    """The author is not one of the bot owners."""


class CheckAnyFailure(CheckFailure):
    """Every check in a ``check_any`` group failed."""

    def __init__(
        self,
        checks: list[object] | None = None,
        errors: list[BaseException] | None = None,
        **fields: Any,
    ) -> None:
        super().__init__(
            "none of the checks passed", checks=checks or [], errors=errors or [], **fields
        )
        self.checks = checks or []
        self.errors = errors or []


class CommandOnCooldown(CheckFailure):
    """The command is cooling down for this bucket."""

    def __init__(self, retry_after: float, **fields: Any) -> None:
        super().__init__(
            f"command on cooldown for {retry_after:.2f}s", retry_after=retry_after, **fields
        )
        self.retry_after = retry_after


class MaxConcurrencyReached(CheckFailure):
    """Too many invocations of the command are running concurrently."""

    def __init__(self, number: int, per: object = None, **fields: Any) -> None:
        super().__init__(f"max concurrency {number} reached", number=number, per=per, **fields)
        self.number = number
        self.per = per


class CommandInvokeError(CommandError):
    """The command body raised."""

    def __init__(self, original: BaseException, **fields: Any) -> None:
        super().__init__(f"command raised {original!r}", original=original, **fields)
        self.original = original


class ExtensionError(CommandError):
    """Base class for extension-loader errors."""


class ExtensionNotLoaded(ExtensionError):
    """The extension is not currently loaded."""


class ExtensionAlreadyLoaded(ExtensionError):
    """The extension is already loaded."""


class ExtensionFailed(ExtensionError):
    """Loading, unloading or reloading an extension failed; state was rolled back."""

    def __init__(self, name: str, original: BaseException | None = None, **fields: Any) -> None:
        super().__init__(
            f"extension {name!r} failed: {original!r}", name=name, original=original, **fields
        )
        self.name = name
        self.original = original
