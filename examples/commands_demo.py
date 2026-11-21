"""M5 demo: commands, cogs and a physics-aligned loop without a server.

Run with ``python examples/commands_demo.py``. Dispatch is normally driven by chat, but
``dispatch_command`` exercises the same path offline.
"""

from __future__ import annotations

import asyncio

from pyflayer.ext import commands, tasks


class Greeter(commands.Cog):
    """A cog that greets players and counts ticks."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.ticks = 0
        self.counter.start()

    @commands.command(brief="Greet a player")
    async def greet(self, ctx: commands.Context, name: str = "world") -> None:
        await ctx.reply(f"Hello, {name}!")

    @commands.command()
    @commands.cooldown(1, 2, commands.BucketType.player)
    async def roll(self, ctx: commands.Context, sides: commands.Range[int, 2, 100] = 6) -> None:
        await ctx.reply(f"Rolled a {sides}-sided die: {self.ticks % sides + 1}")

    @commands.Cog.listener()
    async def on_physics_tick(self, event: object) -> None:
        self.ticks += 1

    @tasks.loop(ticks=5)
    async def counter(self) -> None:
        # Runs every five physics ticks.
        pass


async def setup(bot: commands.Bot) -> None:
    """Extension entry point; a server would load this with ``bot.load_extension``."""
    await bot.add_cog(Greeter(bot))


class DemoBot(commands.Bot):
    """Prints outbound chat instead of opening a connection."""

    async def chat(self, message: str) -> None:
        print(f"[chat] {message}")

    async def send_command(self, command: str) -> None:
        print(f"[command] {command}")


async def main() -> None:
    bot = DemoBot("Steve", host="localhost", use_srv=False)
    await setup(bot)
    await bot.dispatch_command("greet Alex", author="Alex", is_whisper=True)
    await bot.dispatch_command("roll 20", author="Alex", is_whisper=True)
    await bot.dispatch_command("help", author="Alex", is_whisper=True)
    print(commands.format_help(bot))
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
