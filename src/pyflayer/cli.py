"""Command line client: join a server and print chat.

Examples:
    pyflayer-connect play.pika-network.net --username Steve --timeout 30
    python -m pyflayer.cli play.pika-network.net --username Steve --chat "/register a b"
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

from pyflayer._internal.log import configure
from pyflayer.bot.bot import Bot
from pyflayer.errors import PyFlayerError
from pyflayer.events.catalog import ChatEvent, DisconnectEvent, KickEvent, SpawnEvent

__all__ = ["main"]


async def _join(args: argparse.Namespace) -> int:
    bot = Bot(
        args.username,
        host=args.host,
        port=args.port,
        version=args.version,
        use_srv=not args.no_srv,
        reconnect=args.reconnect,
    )

    @bot.event
    async def on_chat(event: ChatEvent) -> None:
        message = event.message
        if message.sender:
            print(f"<{message.sender}> {message.content}")
        else:
            print(f"[{message.position}] {message.content}")

    @bot.event
    async def on_spawn(event: SpawnEvent) -> None:
        position = event.position
        print(f"spawned at ({position.x:.1f}, {position.y:.1f}, {position.z:.1f})")

    @bot.event
    async def on_kick(event: KickEvent) -> None:
        print(f"kicked: {event.reason_text}", file=sys.stderr)

    @bot.event
    async def on_disconnect(event: DisconnectEvent) -> None:
        print(f"disconnected: {event.reason}", file=sys.stderr)

    try:
        join = await bot.connect()
        print(
            f"joined {args.host} as {bot.username} "
            f"(entity {join.entity_id}, gamemode {join.game_mode}, dimension {join.dimension})"
        )
        if args.chat:
            if args.chat.startswith("/"):
                await bot.send_command(args.chat)
            else:
                await bot.chat(args.chat)
        try:
            async with asyncio.timeout(args.timeout):
                await bot.run()
        except TimeoutError:
            print(f"done after {args.timeout:.0f}s")
    finally:
        await bot.close()
        await bot.events.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Join a Minecraft Java server and print chat")
    parser.add_argument("host", help="hostname or IP")
    parser.add_argument("--username", "-u", required=True, help="offline-mode username")
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--version", default="1.8.9")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to stay connected")
    parser.add_argument("--chat", help="send this message/command after joining")
    parser.add_argument("--no-srv", action="store_true")
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    configure(logging.DEBUG if args.verbose else logging.INFO)
    try:
        return asyncio.run(_join(args))
    except (PyFlayerError, OSError, TimeoutError) as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
