"""discord.py-inspired command layer (no prefix, not a port).

Public surface:
    commands.Bot, commands.Cog, commands.Context
    commands.command, commands.group, commands.listener
    commands.Converter, commands.Greedy, commands.Range, commands.Player
    commands.check, commands.check_any, commands.cooldown, commands.max_concurrency
    commands.is_owner, commands.in_dimension, commands.has_player_nearby
    commands.FlagConverter, commands.flag, commands.BucketType
    the :mod:`~pyflayer.ext.commands.errors` tree and :class:`HelpCommand`
"""

from __future__ import annotations

from pyflayer.ext.commands.bot import Bot
from pyflayer.ext.commands.checks import (
    BucketType,
    Check,
    Cooldown,
    CooldownMapping,
    check,
    check_any,
    cooldown,
    has_player_nearby,
    in_dimension,
    is_owner,
    max_concurrency,
)
from pyflayer.ext.commands.cog import Cog, CogMeta, listener
from pyflayer.ext.commands.context import Context
from pyflayer.ext.commands.converters import Converter, Greedy, Player, Range, convert
from pyflayer.ext.commands.core import Command, Group, Parameter, command, group
from pyflayer.ext.commands.errors import (
    BadArgument,
    BadUnionArgument,
    CheckAnyFailure,
    CheckFailure,
    CommandError,
    CommandInvokeError,
    CommandNotFound,
    CommandOnCooldown,
    CommandPrefixError,
    ConversionError,
    ExtensionAlreadyLoaded,
    ExtensionError,
    ExtensionFailed,
    ExtensionNotLoaded,
    MaxConcurrencyReached,
    MissingRequiredArgument,
    NotOwner,
    TooManyArguments,
    UserInputError,
)
from pyflayer.ext.commands.flags import Flag, FlagConverter, flag, parse_flags
from pyflayer.ext.commands.help import HelpCommand, format_help
from pyflayer.ext.commands.view import StringView, tokenize

__all__ = [
    "BadArgument",
    "BadUnionArgument",
    "Bot",
    "BucketType",
    "Check",
    "CheckAnyFailure",
    "CheckFailure",
    "Cog",
    "CogMeta",
    "Command",
    "CommandError",
    "CommandInvokeError",
    "CommandNotFound",
    "CommandOnCooldown",
    "CommandPrefixError",
    "Context",
    "ConversionError",
    "Converter",
    "Cooldown",
    "CooldownMapping",
    "ExtensionAlreadyLoaded",
    "ExtensionError",
    "ExtensionFailed",
    "ExtensionNotLoaded",
    "Flag",
    "FlagConverter",
    "Greedy",
    "Group",
    "HelpCommand",
    "MaxConcurrencyReached",
    "MissingRequiredArgument",
    "NotOwner",
    "Parameter",
    "Player",
    "Range",
    "StringView",
    "TooManyArguments",
    "UserInputError",
    "check",
    "check_any",
    "command",
    "convert",
    "cooldown",
    "flag",
    "format_help",
    "group",
    "has_player_nearby",
    "in_dimension",
    "is_owner",
    "listener",
    "max_concurrency",
    "parse_flags",
    "tokenize",
]
