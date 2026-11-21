#!/usr/bin/env python3
"""Join PikaNetwork the way a player does: read chat and type messages from the terminal.

PikaNetwork (``play.pika-network.net``) runs old-school 1.8.x and accepts offline ("cracked")
logins for any username that a premium account has not claimed, so this script needs no account
setup beyond registering in-game:

    python examples/pika_network.py --username Steve --password hunter2

The bot prints everything the server says and forwards each line you type to the server, including
commands (a leading ``/`` is sent as-is). Use ``--microsoft`` for a premium account, which runs the
device-code login the first time.

Notes:
    * PikaNetwork asks unregistered names to run ``/register <password> <password>``; when
      ``--password`` is given the script answers that prompt and logs in after every reconnect.
    * ``--password`` is visible in the shell history and in ``ps``; pass a throwaway account.
    * Ctrl+C leaves the server; the bot stays online only while this process runs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading

from pyflayer import Bot
from pyflayer.errors import KickedError, PyFlayerError
from pyflayer.events import ChatEvent, DeathEvent, DisconnectEvent, KickEvent, SpawnEvent
from pyflayer.protocol.auth import MicrosoftAuth

HOST = "play.pika-network.net"
PORT = 25565
VERSION = "1.8.9"


def print_line(text: str) -> None:
    """Print a server line and flush, so the terminal keeps up with the bot."""
    print(text, flush=True)


async def _send(bot: Bot, text: str) -> None:
    try:
        await bot.chat(text)
    except PyFlayerError as exc:
        print_line(f"could not send: {exc}")


def _read_console(bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
    """Forward terminal input to the server from a daemon thread (so Ctrl+C still works)."""
    for line in sys.stdin:
        text = line.strip()
        if text:
            asyncio.run_coroutine_threadsafe(_send(bot, text), loop)


async def join(args: argparse.Namespace) -> None:
    auth = MicrosoftAuth() if args.microsoft else None
    bot = Bot(
        args.username,
        host=args.host,
        port=args.port,
        version=VERSION,
        auth=auth,
        reconnect=True,
    )
    state = {"registered": False, "logged_in": False}

    @bot.event
    async def on_spawn(event: SpawnEvent) -> None:
        position = event.position
        print_line(f"spawned at ({position.x:.1f}, {position.y:.1f}, {position.z:.1f})")
        if args.password and not state["logged_in"]:
            await bot.chat(f"/login {args.password}")

    @bot.event
    async def on_chat(event: ChatEvent) -> None:
        message = event.message
        print_line(f"<{message.sender}> {message.content}" if message.sender else message.content)
        if not args.password:
            return
        prompt = message.content.lower()
        if not state["registered"] and ("/register" in prompt or "not registered" in prompt):
            state["registered"] = True
            await bot.chat(f"/register {args.password} {args.password}")
        elif not state["logged_in"] and "/login" in prompt:
            state["logged_in"] = True
            await bot.chat(f"/login {args.password}")

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
    try:
        await bot.run()
    except KickedError as exc:
        reason = exc.reason.plain_text() if exc.reason else str(exc)
        print_line(f"kicked by server: {reason}")
    finally:
        await bot.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join PikaNetwork and chat from the terminal")
    parser.add_argument("--username", "-u", required=True, help="in-game name (max 16 chars)")
    parser.add_argument("--password", "-p", help="in-game /register and /login password")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--microsoft", action="store_true", help="premium account (device-code login)"
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(join(args))
    except KeyboardInterrupt:
        print_line("bye")
    except (PyFlayerError, OSError, TimeoutError) as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
