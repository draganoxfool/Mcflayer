# `pyflayer.ext.commands`

The discord.py-inspired command layer. This page documents the public classes and functions; the
[guide](../modules/commands.md) explains usage and the dispatch model.

```python
from pyflayer.ext import commands
```

!!! note "Optional prefix; `command_prefix` is rejected"
    Use `prefix="!"` (or a collection of prefixes) for prefix commands. A message is also a
    command when it is addressed to the bot, matches `trigger=`, or is passed to
    `bot.dispatch_command()`. The discord.py spelling `command_prefix=` raises
    `CommandPrefixError` (a `TypeError`); it is not silently accepted.

## `commands.Bot`

```python
commands.Bot(username=None, *, prefix=None, trigger=None, case_insensitive=True,
             owner_ids=(), help_command=True, **bot_kwargs)
```

A `pyflayer.Bot` subclass that owns a command, cog and extension registry.

::: pyflayer.ext.commands.bot.Bot
    options:
      members:
        - dispatch_command
        - process_message
        - add_command
        - remove_command
        - get_command
        - walk_commands
        - add_cog
        - remove_cog
        - load_extension
        - unload_extension
        - reload_extension
        - on_command_error
        - get_player
        - player_names

## `commands.Context`

::: pyflayer.ext.commands.context.Context
    options:
      members: [reply, send]

## Commands and groups

::: pyflayer.ext.commands.core.Command
    options:
      members: [invoke, can_run, prepare, error, before_invoke, after_invoke, qualified_name, short_doc]

::: pyflayer.ext.commands.core.Group
    options:
      members: [add_command, get_command, walk_commands]
      show_bases: false

::: pyflayer.ext.commands.core.Parameter

::: pyflayer.ext.commands.core.command

::: pyflayer.ext.commands.core.group

## Cogs

::: pyflayer.ext.commands.cog.Cog
    options:
      members: [listener, get_commands, get_listeners, get_loops, cog_load, cog_unload, cog_check,
                cog_before_invoke, cog_after_invoke, cog_command_error, qualified_name]

::: pyflayer.ext.commands.cog.listener

## Converters

::: pyflayer.ext.commands.converters.Converter
    options:
      members: [convert]

::: pyflayer.ext.commands.converters.Greedy

::: pyflayer.ext.commands.converters.Range

## Checks and cooldowns

::: pyflayer.ext.commands.checks.check

::: pyflayer.ext.commands.checks.check_any

::: pyflayer.ext.commands.checks.cooldown

::: pyflayer.ext.commands.checks.max_concurrency

::: pyflayer.ext.commands.checks.is_owner

::: pyflayer.ext.commands.checks.in_dimension

::: pyflayer.ext.commands.checks.has_player_nearby

::: pyflayer.ext.commands.checks.BucketType

::: pyflayer.ext.commands.checks.Cooldown

::: pyflayer.ext.commands.checks.CooldownMapping

## Flags

::: pyflayer.ext.commands.flags.flag

::: pyflayer.ext.commands.flags.Flag

::: pyflayer.ext.commands.flags.FlagConverter

::: pyflayer.ext.commands.flags.parse_flags

## Help

::: pyflayer.ext.commands.help.HelpCommand

::: pyflayer.ext.commands.help.format_help

## Tokenizer

::: pyflayer.ext.commands.view.StringView

::: pyflayer.ext.commands.view.tokenize

## Errors

The full tree lives in `pyflayer.ext.commands.errors` and derives from
[`PyFlayerError`](errors.md#pyflayer.errors.PyFlayerError).

| Error | Meaning |
|---|---|
| `CommandError` | Base for every command error |
| `CommandPrefixError` | `command_prefix=` was passed (also `TypeError`); use `prefix=` |
| `CommandNotFound` | No command matched |
| `UserInputError` | Bad input base |
| `MissingRequiredArgument` | A required parameter was missing |
| `BadArgument` | A converter rejected an argument |
| `TooManyArguments` | Extra positional arguments |
| `BadUnionArgument` | No `Union` member accepted the value |
| `ConversionError` | A converter raised unexpectedly |
| `CheckFailure` | A check returned `False` |
| `NotOwner` | Author is not an owner |
| `CheckAnyFailure` | Every `check_any` predicate failed |
| `CommandOnCooldown` | Cooldown in effect (`retry_after`) |
| `MaxConcurrencyReached` | Too many concurrent invocations |
| `CommandInvokeError` | The command body raised |
| `ExtensionError` | Extension loader base |
| `ExtensionNotLoaded` | Unloading an extension that is not loaded |
| `ExtensionAlreadyLoaded` | Loading an extension twice |
| `ExtensionFailed` | Load/unload/reload failed; state was rolled back |
