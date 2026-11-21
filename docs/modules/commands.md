# Commands (`pyflayer.ext.commands`)

A discord.py-inspired command layer. It keeps the ergonomics that make bots pleasant to write —
decorators, cogs, typed signatures, converters, checks, cooldowns, help — and drops everything that
has no meaning in Minecraft.

!!! note "Optional prefixes, plus addressing"
    Pass `prefix="!"` to accept `!mine stone 8` in public chat. A chat line is also a command when
    it is **addressed to the bot** (a whisper, a name mention, or a `trigger=` match), or when code
    calls `bot.dispatch_command(...)`. Prefixes work in all of those forms. The discord.py spelling
    `command_prefix=` raises `CommandPrefixError` (a `TypeError`) so ported snippets fail loudly.

## Quick start

```python
import pyflayer
from pyflayer.ext import commands, tasks

bot = commands.Bot(version="1.8.9")

class Miner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status.start()

    @commands.Cog.listener()
    async def on_spawn(self, event):
        print("spawned at", event.position)

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.player)
    async def mine(self, ctx, block: str, count: commands.Range[int, 1, 64] = 1):
        await ctx.reply(f"mining {count} {block}")

    @tasks.loop(seconds=30)
    async def status(self):
        await self.bot.chat(f"health={self.bot.health}")

async def setup(bot):
    await bot.add_cog(Miner(bot))
```

Address it in chat:

```text
Steve: mine stone 8
```

or dispatch programmatically:

```python
await bot.dispatch_command("mine stone 8", author="Alex", is_whisper=True)
```

## Dispatch rules

| Source | Addressed when | Parsed as |
|---|---|---|
| Prefix | A configured `prefix=` starts the line | prefix stripped, rest parsed |
| Whisper | Always | optional prefix stripped, rest parsed |
| Public chat | The bot's name appears as a token (`Steve`, `@Steve`, `<Steve>`) | name and optional prefix stripped |
| `trigger=` | A configured `str`/regex matches | matched text and optional prefix stripped |
| Programmatic | `await bot.dispatch_command(text, author=...)` | whole text parsed |

`ctx.prefix` is the prefix that matched, or `None` for an address-only invocation. Messages from
the bot itself and server/system lines (no `sender`) are ignored.

## Commands and signatures

`@commands.command()` wraps an `async def` whose first parameter after `ctx` is parsed from chat.
The parser understands:

| Syntax | Behaviour |
|---|---|
| `name: str`, `count: int` | one token, converted |
| `words: commands.Greedy[str]` | all remaining tokens as a list |
| `text: str = "hi"` | optional, with a default |
| `*, text: str` | keyword-only (consumes one token) |
| `sides: commands.Range[int, 2, 100]` | converted, then bounds-checked |
| `opts: MyFlags` | a `FlagConverter` consuming the rest as `--flag value` pairs |

```python
@commands.command(aliases=["pong"], brief="Check latency")
async def ping(ctx):
    await ctx.reply("pong")

@commands.group(invoke_without_command=True)
async def admin(ctx):
    await ctx.reply("admin: say | kick")

@admin.command(name="say")
async def admin_say(ctx, text: commands.Greedy[str]):
    await ctx.send(" ".join(text))
```

`ctx.reply()` answers a whisper with a whisper and public chat with public chat; `ctx.send()`
always uses public chat. Both go through the bot's `ChatQueue`, so replies are rate-limited.

## Converters

Resolution order: explicit `Annotated`/`Converter` → built-in map → `Literal`/enums → callable.

Built-ins: `str`, `int`, `float`, `bool`, `Dimension`, `GameMode`, `Player` (tab-list lookup),
`Literal[...]`, `Optional[T]`, `Union[...]`, `Greedy[T]`, `Range[T, lo, hi]`, and `FlagConverter`
subclasses. A converter is any object with `async def convert(self, ctx, argument)`.

Failures become `BadArgument` (or `ConversionError` when a converter itself crashes); both are
`CommandError`s routed through the error chain.

## Checks and cooldowns

```python
from pyflayer.ext import commands

@commands.command()
@commands.check(lambda ctx: ctx.bot.health > 10)
@commands.cooldown(1, 5, commands.BucketType.player)
async def heal(ctx): ...

@commands.command()
@commands.is_owner()
async def stop(ctx): ...
```

`BucketType.player` keys limits by sender; `default` and `global_` are global (Minecraft has no
channels). Cooldowns use the bot's injected `Clock`, so they are deterministic under `FakeClock`.
Also available: `check_any`, `max_concurrency`, `in_dimension`, `has_player_nearby`.

## Error handling

Errors travel `bot.on_command_error` → `cog.cog_command_error` → `@command.error`. The first handler
that returns stops the chain; an unhandled error is logged.

```python
@bot.on_command_error
async def on_error(ctx, error):
    await ctx.reply(f"error: {error}")
```

The error tree lives in `pyflayer.ext.commands.errors`: `CommandError` → `UserInputError`
(`MissingRequiredArgument`, `BadArgument`, …), `CheckFailure` (`NotOwner`, `CommandOnCooldown`,
`MaxConcurrencyReached`), `CommandInvokeError`, and the extension errors.

## Cogs

A `Cog` groups commands, listeners and loops. `CogMeta` collects them at class creation.

```python
class Greeter(commands.Cog):
    @commands.Cog.listener()
    async def on_chat(self, event): ...

    @commands.command()
    async def greet(self, ctx, name: str = "world"):
        await ctx.reply(f"hello {name}")
```

`await bot.add_cog(cog)` registers its commands, subscribes its listeners (`owner=cog`) and resumes
its loops; `await bot.remove_cog(name)` reverses all of it.

## Extensions and hot reload

An extension module defines `async def setup(bot)` and optionally `async def teardown(bot)`.

```python
await bot.load_extension("my_bot.features")
await bot.reload_extension("my_bot.features")
await bot.unload_extension("my_bot.features")
```

`load_extension` tracks everything registered during `setup` and rolls it back when setup raises.
`reload_extension` is atomic: it unloads, purges the extension's `sys.modules` subtree, re-imports,
and on failure restores the previous module, cogs and commands before raising `ExtensionFailed`.
Twenty reload cycles leave no leaked subscriptions or commands.

## Flags

```python
class Options(commands.FlagConverter):
    count: int = commands.flag(default=1)
    silent: bool = commands.flag(default=False)

@commands.command()
async def broadcast(ctx, *, opts: Options):
    await ctx.reply(f"count={opts.count} silent={opts.silent}")
```

`--count 5 --silent` and `--count=5` are both accepted.

## Help

`commands.Bot` adds a `help` command by default (`help_command=False` disables it). It is plain text
that fits a chat line, not paginated embeds. `commands.format_help(bot)` returns the same string.

## Deferred discord.py surface

Documented, not stubbed: slash commands/`app_commands`, interactions, views/modals/buttons,
webhooks, threads, permissions/roles/guilds, `Intents`, the `Client`/`Bot` split, and
discord.py-compatible import aliases. See [Migrating from discord.py](../migrating-from-discordpy.md).

## Limitations

- Command arguments come from chat text only; there is no interaction payload.
- `tasks.loop(time=...)` is accepted for familiarity but not scheduled.
- Public-chat addressing is token-based; plugin chat that rewrites names needs `trigger=`.
- There is no permission hierarchy; use `is_owner`, `check`, and world checks.
