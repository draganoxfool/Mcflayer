# Migrating from discord.py
mcflayer borrows selected discord.py patterns, but is not a drop-in replacement. Its command API
targets Minecraft chat and world state, not Discord interactions or permissions.

## What carries over

| discord.py | mcflayer |
|---|---|
| `commands.Bot(...)` | `commands.Bot(...)` (a `pyflayer.Bot`) |
| `@bot.command()` | `@commands.command()` / `@bot.command()` |
| `@commands.group()` / `@group.command()` | same |
| `commands.Cog`, `Cog.listener()` | same |
| `@commands.command()` type hints | parsed into typed parameters |
| converters, `Greedy`, `Range` | same names and behaviour |
| `@commands.check`, `cooldown`, `max_concurrency` | same |
| `commands.BucketType` | same (`player`, `default`, `global_`) |
| `tasks.loop(seconds=...)` | same pattern, plus `ticks=` |
| `setup(bot)` / `teardown(bot)` | same, with atomic hot reload |
| `bot.load_extension` / `unload` / `reload` | same |
| `ctx.reply()` / `ctx.send()` | same (rate-limited chat) |

## What is gone

| Removed | Why | Replacement |
|---|---|---|
| `command_prefix=` | The discord.py spelling is rejected (`CommandPrefixError`, a `TypeError`). Minecraft chat has no implicit prefix, so prefixes are opt-in. | Use `prefix="!"`, address the bot by whisper/name mention, or `bot.dispatch_command()` |
| Slash commands / `app_commands` | No interactions in the Java chat protocol. | — |
| Views, modals, buttons, select menus | No interaction payloads. | Commands + chat |
| Webhooks, threads, forums | No such concepts. | — |
| Permissions, roles, guilds | Minecraft has no role hierarchy. | `is_owner`, `check`, world checks |
| `Intents`, gateway, sharding, resume | Not a gateway client. | `Bot` owns one connection |
| `Client`/`Bot` split | One composition root. | `commands.Bot` |
| `discord` import aliases | Not a compatibility target. | `pyflayer.ext.commands` |
| `tasks.loop(time=...)` scheduling | Not scheduled. | `seconds` / `ticks` |
| Extension `Bot` subclass hooks (`on_message`) | No `on_message`; chat is a typed event. | `@Cog.listener()` `on_chat` |

## Dispatch differences

discord.py:

```python
bot = commands.Bot(command_prefix="!")


@bot.command()
async def ping(ctx):
    await ctx.send("pong")


# "!ping" in a Discord channel
```

mcflayer:

```python
bot = commands.Bot(version="1.8.9", prefix="!")  # prefix is optional


@bot.command()
async def ping(ctx):
    await ctx.reply("pong")


# A configured prefix or address/whisper can dispatch a chat command.
# Code can dispatch directly with await bot.dispatch_command(...).
```

- `ctx.prefix` is the matched prefix, or `None` when only addressing matched.
- `ctx.author` is a sender **name** (or `None` for system lines), not a `Member`.
- `ctx.channel`/`ctx.guild` do not exist.
- `ctx.reply()` answers whispers privately and public chat publicly.

## Porting checklist

1. Replace `command_prefix=` with `prefix=` (or omit it and use address-based commands). Add
   `trigger=` only if the server rewrites chat.
2. Replace `ctx.send`/`reply` bodies that assumed embeds with plain text.
3. Replace `Member`/`Role`/`Permission` checks with `is_owner`/`check`/world checks.
4. Move `on_message` logic into an `on_chat` listener that calls `bot.dispatch_command`.
5. Replace `discord.ext.tasks.loop(time=…)` with `seconds` or `ticks`.
6. Keep cogs and extensions; both reload atomically.
