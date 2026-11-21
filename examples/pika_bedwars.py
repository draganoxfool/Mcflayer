#!/usr/bin/env python3
"""BedWars example for pyflayer.

Demonstrates inventory-slot management, window clicking, item use,
block placing, and block breaking on PikaNetwork's BedWars (1.8.9).

Features:
  - Join a BedWars game
  - Open a chest and click/sift-click slots
  - Use an item (sword) with `use_item()`
  - Place a block (bed) with `place_block()`
  - Break a block with `break_block()`

Run:
    python examples/pika_bedwars.py --username Steve --password hunter2

Note: The --password is visible in shell history; use a throwaway account.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading

from pyflayer import Bot
from pyflayer.bot.interactions import break_block, place_block, use_item
from pyflayer.bot.inventory import ClickMode
from pyflayer.bot.windows import click_slot, close_window, shift_click_slot
from pyflayer.errors import KickedError, PyFlayerError
from pyflayer.events import ChatEvent, DeathEvent, DisconnectEvent, KickEvent, SpawnEvent
from pyflayer.protocol.auth import MicrosoftAuth

HOST = "play.pika-network.net"
PORT = 25565
VERSION = "1.8.9"

BED_POS = (0, 4, 0)  # example bed coordinates in BedWars


def print_line(text: str) -> None:
    """Print a server line and flush."""
    print(text, flush=True)


async def _send(bot: Bot, text: str) -> None:
    try:
        await bot.chat(text)
    except PyFlayerError as exc:
        print_line(f"could not send: {exc}")


def _read_console(bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
    """Forward terminal input to the server from a daemon thread."""
    for line in sys.stdin:
        text = line.strip()
        if text:
            asyncio.run_coroutine_threadsafe(_send(bot, text), loop)


async def join_bedwars(args: argparse.Namespace) -> Bot:
    auth = MicrosoftAuth() if args.microsoft else None
    bot = Bot(
        args.username,
        host=args.host,
        port=args.port,
        version=VERSION,
        auth=auth,
        reconnect=True,
    )

    @bot.event
    async def on_spawn(event: SpawnEvent) -> None:
        print_line(
            f"spawned at ({event.position.x:.1f}, {event.position.y:.1f}, {event.position.z:.1f})"
        )
        # Open bed inventory (BedWars beds use window type 21 / chest with delay)
        # We'll demonstrate by looking for a chest window on connect

    @bot.event
    async def on_chat(event: ChatEvent) -> None:
        message = event.message
        print_line(f"<{message.sender}> {message.content}" if message.sender else message.content)

    @bot.event
    async def on_death(event: DeathEvent) -> None:
        print_line("you died; respawning")

    @bot.event
    async def on_kick(event: KickEvent) -> None:
        print_line(f"kicked: {event.reason_text}")

    @bot.event
    async def on_disconnect(event: DisconnectEvent) -> None:
        print_line(f"disconnected: {event.reason}")

    join_event = await bot.connect()
    print_line(
        f"joined {args.host} as {bot.username} (entity {join_event.entity_id}, "
        f"gamemode {join_event.game_mode}); type chat or commands, Ctrl+C to quit"
    )
    threading.Thread(
        target=_read_console, args=(bot, asyncio.get_running_loop()), daemon=True
    ).start()
    return bot


async def demo_inventory_interactions(bot: Bot) -> None:
    """Demonstrate inventory window clicking and item use."""

    # Wait a moment for any initial chest window to open
    await asyncio.sleep(2)

    # Find open windows and demonstrate clicking
    for window_id, window in bot.inventory.windows.items():
        print_line(
            f"Window opened: kind={window.kind}, "
            f"container_slots={window.container_slots}, window_id={window_id}"
        )
        # Example: click the first slot (index 0) with left click, action 0
        # This works for chests (27 slots), furnaces (3 slots), etc.
        await click_slot(bot, window_id, 0, mode=ClickMode.LEFT)
        print_line(f"clicked slot 0 in window {window_id}")

        # Example: shift-click the last available slot
        last = window.container_slots - 1
        if last >= 0:
            await shift_click_slot(bot, window_id, last)
            print_line(f"shift-clicked slot {last} in window {window_id}")

    # Close any open window
    await close_window(bot)
    print_line("closed window")


async def demo_item_use(bot: Bot) -> None:
    """Demonstrate using an item (e.g., sword) with the block_place sentinel."""
    await asyncio.sleep(1)
    print_line("using item (sword) ...")
    await use_item(bot)
    print_line("item used (sword swing sent)")


async def demo_block_actions(bot: Bot) -> None:
    """Demonstrate placing and breaking blocks."""
    await asyncio.sleep(1)

    # Place a bed at the BedWars bed position
    print_line(f"placing bed at {BED_POS} ...")
    await place_block(bot, *BED_POS)
    print_line("bed placement packet sent")

    # Break the same bed
    await asyncio.sleep(0.5)
    print_line(f"breaking block at {BED_POS} ...")
    await break_block(bot, *BED_POS)
    print_line("block break packet sent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join PikaNetwork BedWars and demo actions")
    parser.add_argument("--username", "-u", required=True, help="in-game name (max 16 chars)")
    parser.add_argument("--password", "-p", help="/register and /login password")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--microsoft", action="store_true", help="premium account")
    args = parser.parse_args(argv)

    async def run_bot() -> None:
        bot = await join_bedwars(args)

        try:
            # Demo the new modules
            await demo_inventory_interactions(bot)
            await demo_item_use(bot)
            await demo_block_actions(bot)

            # Keep the bot running for chat
            print_line("running... type chat messages, Ctrl+C to quit")
            await bot.run()
        except KickedError as exc:
            reason = exc.reason.plain_text() if exc.reason else str(exc)
            print_line(f"kicked by server: {reason}")
        finally:
            await bot.close()

    asyncio.run(run_bot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
