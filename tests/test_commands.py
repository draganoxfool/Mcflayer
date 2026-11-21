"""M5 tests: command parsing, cogs, extensions, checks, loops and flags."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from typing import Annotated, Any

import pytest

import pyflayer.ext.commands as commands
import pyflayer.ext.tasks as tasks
from pyflayer._internal.clock import FakeClock
from pyflayer.events.catalog import ChatEvent, PhysicsTickEvent
from pyflayer.ext.commands.errors import (
    CommandNotFound,
    CommandOnCooldown,
    CommandPrefixError,
    ExtensionFailed,
    ExtensionNotLoaded,
)
from pyflayer.ext.commands.view import StringView, tokenize
from pyflayer.models.chat import ChatMessage
from pyflayer.models.vec3 import Vec3


class _UpperConverter:
    async def convert(self, ctx: commands.Context, argument: str) -> str:
        del ctx
        return argument.upper()


def make_bot(**kwargs: Any) -> commands.Bot:
    bot = commands.Bot("Steve", host="localhost", use_srv=False, **kwargs)
    return bot


# --------------------------------------------------------------------------- view / tokenizer


def test_tokenize_handles_quotes_and_escapes() -> None:
    assert tokenize('say "hello world"') == ["say", "hello world"]
    assert tokenize(r'say hello\ world') == ["say", "hello world"]
    assert tokenize('a "" b') == ["a", "", "b"]


def test_string_view_reads_quoted_words() -> None:
    view = StringView('cmd "two words" tail')
    assert view.read() == "cmd"
    assert view.get_quoted_word() == "two words"
    assert view.get_quoted_word() == "tail"
    assert view.eof


# --------------------------------------------------------------------------- prefix / dispatch


def test_command_prefix_is_rejected() -> None:
    with pytest.raises(CommandPrefixError):
        commands.Bot("Steve", host="localhost", command_prefix="!")
    assert issubclass(CommandPrefixError, TypeError)


async def test_whisper_dispatch() -> None:
    bot = make_bot()
    seen: list[str] = []

    @bot.command()
    async def ping(ctx: commands.Context) -> None:
        seen.append(ctx.sender_name)

    await bot.process_message(ChatMessage(content="ping", sender="Alex", is_whisper=True))
    assert seen == ["Alex"]


async def test_name_mention_dispatch_strips_name() -> None:
    bot = make_bot()
    got: list[str] = []

    @bot.command()
    async def echo(ctx: commands.Context, text: str) -> None:
        got.append(text)

    await bot.process_message(ChatMessage(content="Steve echo hello", sender="Alex"))
    assert got == ["hello"]


async def test_decorated_name_mentions_dispatch() -> None:
    bot = make_bot()
    got: list[str] = []

    @bot.command()
    async def echo(ctx: commands.Context, text: str) -> None:
        got.append(text)

    for content in ("@Steve echo hello", "<Steve> echo hello", "@Steve: echo hello", "Steve, echo hi"):
        await bot.process_message(ChatMessage(content=content, sender="Alex"))
    assert got == ["hello", "hello", "hello", "hi"]


async def test_similar_player_name_is_not_a_mention() -> None:
    bot = make_bot()
    called: list[int] = []

    @bot.command()
    async def echo(ctx: commands.Context, text: str) -> None:
        called.append(1)

    await bot.process_message(ChatMessage(content="Steve2 echo hello", sender="Alex"))
    assert called == []


async def test_unaddressed_message_is_ignored() -> None:
    bot = make_bot()
    called: list[int] = []

    @bot.command()
    async def ping(ctx: commands.Context) -> None:
        called.append(1)

    await bot.process_message(ChatMessage(content="ping", sender="Alex"))
    assert called == []


async def test_alias_and_programmatic_dispatch() -> None:
    bot = make_bot()
    called: list[str] = []

    @bot.command(aliases=["pong"])
    async def ping(ctx: commands.Context) -> None:
        called.append(ctx.invoked_with)

    await bot.dispatch_command("pong", author="Alex", is_whisper=True)
    assert called == ["pong"]


async def test_unknown_command_raises() -> None:
    bot = make_bot()
    with pytest.raises(CommandNotFound):
        await bot.dispatch_command("nope", author="Alex", is_whisper=True)


# --------------------------------------------------------------------------- converters


async def test_converters_and_range() -> None:
    bot = make_bot()
    got: list[tuple[int, int]] = []

    @bot.command()
    async def give(ctx: commands.Context, count: int, bounded: commands.Range[int, 1, 10] = 1) -> None:
        got.append((count, bounded))

    await bot.dispatch_command("give 5 10", author="Alex", is_whisper=True)
    assert got == [(5, 10)]


async def test_range_rejects_out_of_bounds() -> None:
    bot = make_bot()
    errors: list[BaseException] = []

    @bot.command()
    async def give(ctx: commands.Context, count: commands.Range[int, 1, 3]) -> None:
        pass

    @bot.on_command_error
    async def on_error(ctx: commands.Context, error: BaseException) -> None:
        errors.append(error)

    await bot.dispatch_command("give 9", author="Alex", is_whisper=True)
    assert errors and errors[0].__class__.__name__ == "BadArgument"


async def test_greedy_collects_remaining_tokens() -> None:
    bot = make_bot()
    got: list[list[str]] = []

    @bot.command()
    async def say(ctx: commands.Context, words: commands.Greedy[str]) -> None:
        got.append(words)

    await bot.dispatch_command('say one "two three" four', author="Alex", is_whisper=True)
    assert got == [["one", "two three", "four"]]


async def test_annotated_converter_overrides_base_annotation() -> None:
    bot = make_bot()
    got: list[str] = []

    @bot.command()
    async def shout(ctx: commands.Context, word: Annotated[str, _UpperConverter()]) -> None:
        got.append(word)

    await bot.dispatch_command("shout hello", author="Alex", is_whisper=True)
    assert got == ["HELLO"]


async def test_keyword_only_parameter() -> None:
    bot = make_bot()
    got: list[dict[str, str]] = []

    @bot.command()
    async def note(ctx: commands.Context, *, text: str) -> None:
        got.append({"text": text})

    await bot.dispatch_command("note hi", author="Alex", is_whisper=True)
    assert got == [{"text": "hi"}]


async def test_missing_required_argument_reports_error() -> None:
    bot = make_bot()
    errors: list[BaseException] = []

    @bot.command()
    async def need(ctx: commands.Context, value: int) -> None:
        pass

    @bot.on_command_error
    async def on_error(ctx: commands.Context, error: BaseException) -> None:
        errors.append(error)

    await bot.dispatch_command("need", author="Alex", is_whisper=True)
    assert errors and errors[0].__class__.__name__ == "MissingRequiredArgument"


# --------------------------------------------------------------------------- checks / cooldown


async def test_check_failure_blocks_invocation() -> None:
    bot = make_bot()
    called: list[int] = []

    def never(ctx: commands.Context) -> bool:
        return False

    @bot.command()
    @commands.check(never)
    async def secret(ctx: commands.Context) -> None:
        called.append(1)

    errors: list[BaseException] = []

    @bot.on_command_error
    async def on_error(ctx: commands.Context, error: BaseException) -> None:
        errors.append(error)

    await bot.dispatch_command("secret", author="Alex", is_whisper=True)
    assert called == []
    assert errors and errors[0].__class__.__name__ == "CheckFailure"


async def test_max_concurrency_wait_queues_instead_of_rejecting() -> None:
    bot = make_bot()
    started: list[str] = []
    finished: list[str] = []
    release = asyncio.Event()

    @bot.command()
    @commands.max_concurrency(1, commands.BucketType.global_, wait=True)
    async def slow(ctx: commands.Context) -> None:
        started.append(ctx.sender_name)
        await release.wait()
        finished.append(ctx.sender_name)

    first = asyncio.create_task(
        bot.dispatch_command("slow", author="Alex", is_whisper=True)
    )
    await _settle()
    second = asyncio.create_task(
        bot.dispatch_command("slow", author="Bob", is_whisper=True)
    )
    await _settle()
    assert started == ["Alex"]

    release.set()
    await asyncio.gather(first, second)
    assert started == ["Alex", "Bob"]
    assert finished == ["Alex", "Bob"]


async def test_cooldown_uses_injected_clock() -> None:
    clock = FakeClock()
    bot = make_bot(clock=clock)
    calls: list[int] = []
    errors: list[BaseException] = []

    @bot.command()
    @commands.cooldown(1, 5, commands.BucketType.player)
    async def spam(ctx: commands.Context) -> None:
        calls.append(1)

    @bot.on_command_error
    async def on_error(ctx: commands.Context, error: BaseException) -> None:
        errors.append(error)

    await bot.dispatch_command("spam", author="Alex", is_whisper=True)
    await bot.dispatch_command("spam", author="Alex", is_whisper=True)
    assert calls == [1]
    assert isinstance(errors[-1], CommandOnCooldown)
    clock.advance(5.0)
    await bot.dispatch_command("spam", author="Alex", is_whisper=True)
    assert calls == [1, 1]


# --------------------------------------------------------------------------- groups


async def test_group_subcommand_dispatch() -> None:
    bot = make_bot()
    got: list[str] = []

    @bot.group()
    async def admin(ctx: commands.Context) -> None:
        got.append("group")

    @admin.command(name="say")
    async def admin_say(ctx: commands.Context, text: str) -> None:
        got.append(text)

    await bot.dispatch_command("admin say hello", author="Alex", is_whisper=True)
    assert got == ["hello"]


async def test_group_subcommand_respects_case_insensitive_setting() -> None:
    bot = make_bot()
    got: list[str] = []

    @bot.group()
    async def admin(ctx: commands.Context) -> None:
        pass

    @admin.command(name="say")
    async def admin_say(ctx: commands.Context, text: str) -> None:
        got.append(text)

    await bot.dispatch_command("ADMIN SAY hello", author="Alex", is_whisper=True)
    assert got == ["hello"]


# --------------------------------------------------------------------------- cogs


async def test_cog_registers_commands_and_listeners() -> None:
    bot = make_bot()
    events: list[str] = []

    class MyCog(commands.Cog):
        @commands.Cog.listener()
        async def on_chat(self, event: ChatEvent) -> None:
            events.append(event.message.content)

        @commands.command()
        async def hello(self, ctx: commands.Context) -> None:
            await ctx.reply("hi")

    cog = MyCog(bot)
    await bot.add_cog(cog)
    assert "hello" in bot.commands
    assert "mycog" in bot.cogs

    bot.events.dispatch(ChatEvent(message=ChatMessage(content="anything", sender="Alex")))
    await _settle()
    assert events == ["anything"]

    await bot.remove_cog("mycog")
    assert "hello" not in bot.commands
    assert bot.events.subscription_count == 1  # only the bot's own ChatEvent listener


async def test_cog_command_error_default_allows_command_handler() -> None:
    bot = make_bot()
    errors: list[BaseException] = []

    class FailingCog(commands.Cog):
        @commands.command()
        async def boom(self, ctx: commands.Context) -> None:
            raise ValueError("boom")

        @boom.error
        async def on_boom_error(self, ctx: commands.Context, error: BaseException) -> None:
            del ctx
            errors.append(error)

    await bot.add_cog(FailingCog(bot))
    await bot.dispatch_command("boom", author="Alex", is_whisper=True)
    assert len(errors) == 1
    assert isinstance(errors[0], commands.CommandInvokeError)


# --------------------------------------------------------------------------- extensions


EXTENSION = textwrap.dedent(
    '''
    from pyflayer.ext import commands

    class ExtCog(commands.Cog):
        @commands.Cog.listener()
        async def on_chat(self, event):
            pass

        @commands.command()
        async def ping(self, ctx):
            await ctx.reply("pong")

    async def setup(bot):
        await bot.add_cog(ExtCog(bot))

    async def teardown(bot):
        pass
    '''
)


async def test_extension_load_unload_and_reload_no_leaks(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Any) -> None:
    (tmp_path / "extmod.py").write_text(EXTENSION)
    monkeypatch.syspath_prepend(str(tmp_path))
    bot = make_bot()
    baseline_subs = bot.events.subscription_count
    baseline_commands = len(bot.commands)

    await bot.load_extension("extmod")
    subs = bot.events.subscription_count
    command_count = len(bot.commands)
    assert subs == baseline_subs + 1
    assert command_count == baseline_commands + 1
    assert "ping" in bot.commands

    for _ in range(20):
        await bot.reload_extension("extmod")
        await _settle()
        assert bot.events.subscription_count == subs
        assert len(bot.commands) == command_count
        assert bot.events.task_count == 0

    await bot.unload_extension("extmod")
    assert bot.events.subscription_count == baseline_subs
    assert len(bot.commands) == baseline_commands
    with pytest.raises(ExtensionNotLoaded):
        await bot.unload_extension("extmod")


async def test_broken_reload_rolls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    module = tmp_path / "brokenmod.py"
    module.write_text(EXTENSION)
    monkeypatch.syspath_prepend(str(tmp_path))
    bot = make_bot()
    await bot.load_extension("brokenmod")
    assert "ping" in bot.commands

    module.write_text(
        textwrap.dedent(
            '''
            from pyflayer.ext import commands

            class BrokenCog(commands.Cog):
                @commands.command()
                async def broken(self, ctx):
                    pass

            async def setup(bot):
                await bot.add_cog(BrokenCog(bot))
                raise RuntimeError("boom")
            '''
        )
    )
    with pytest.raises(ExtensionFailed):
        await bot.reload_extension("brokenmod")
    assert "ping" in bot.commands
    assert "broken" not in bot.commands
    assert "brokencog" not in bot.cogs


# --------------------------------------------------------------------------- flags / help


async def test_flag_converter_parses_values() -> None:
    class Options(commands.FlagConverter):
        count: int = commands.flag(default=1)
        silent: bool = commands.flag(default=False)

    bot = make_bot()
    ctx = commands.Context(
        bot=bot,
        message=ChatMessage(content="", sender="Alex"),
        author="Alex",
        sender_name="Alex",
        invoked_with="x",
        command=None,
        view=StringView(""),
    )
    options = await Options().convert(ctx, "--count 5 --silent")
    assert options.count == 5
    assert options.silent is True


async def test_help_lists_commands() -> None:
    bot = make_bot()

    @bot.command(brief="Say hello")
    async def hello(ctx: commands.Context) -> None:
        pass

    text = commands.format_help(bot)
    assert "hello" in text
    assert "Say hello" in text


# --------------------------------------------------------------------------- tasks.loop


async def test_loop_aligned_to_physics_ticks() -> None:
    bot = make_bot()
    ticks: list[int] = []

    class TickCog(commands.Cog):
        def __init__(self, bot: commands.Bot) -> None:
            super().__init__(bot)
            self.runs = 0

        @tasks.loop(ticks=2, count=3)
        async def ticker(self) -> None:
            self.runs += 1
            ticks.append(self.runs)

    cog = TickCog(bot)
    await bot.add_cog(cog)
    cog.ticker.start()
    await _settle()

    for index in range(10):
        bot.events.dispatch(
            PhysicsTickEvent(tick=index, position=Vec3(0, 64, 0), on_ground=True)
        )
        await _settle()

    assert ticks == [1, 2, 3]
    assert not cog.ticker.is_running()


async def test_loop_descriptor_is_stable_and_remove_cog_cancels_it() -> None:
    clock = FakeClock()
    bot = make_bot(clock=clock)

    class CancelCog(commands.Cog):
        def __init__(self, bot: commands.Bot) -> None:
            super().__init__(bot)
            self.runs = 0

        @tasks.loop(seconds=60)
        async def ticker(self) -> None:
            self.runs += 1

    cog = CancelCog(bot)
    await bot.add_cog(cog)
    bound = cog.ticker
    task = bound.start()
    await _settle()

    assert cog.ticker is bound
    assert bound.is_running()
    await bot.remove_cog("cancelcog")
    await _settle()
    await asyncio.gather(task, return_exceptions=True)
    assert task.done()
    assert not bound.is_running()


async def test_standalone_loop_can_be_started() -> None:
    runs: list[int] = []

    @tasks.loop(count=1)
    async def once() -> None:
        runs.append(1)

    await once.start()
    assert runs == [1]
    assert not once.is_running()


async def test_loop_count_with_fake_clock() -> None:
    clock = FakeClock()
    bot = make_bot(clock=clock)

    class TimeCog(commands.Cog):
        def __init__(self, bot: commands.Bot) -> None:
            super().__init__(bot)
            self.runs = 0

        @tasks.loop(seconds=1, count=2)
        async def ticker(self) -> None:
            self.runs += 1

    cog = TimeCog(bot)
    await bot.add_cog(cog)
    cog.ticker.start()
    await _settle()
    # First iteration runs immediately, then waits one second for the second.
    assert cog.runs == 1
    clock.advance(1.0)
    await _settle()
    assert cog.runs == 2


# --------------------------------------------------------------------------- helpers


async def _settle(turns: int = 5) -> None:
    import asyncio

    for _ in range(turns):
        await asyncio.sleep(0)
