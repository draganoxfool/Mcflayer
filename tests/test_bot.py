from __future__ import annotations

import asyncio

import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.bot import Bot
from pyflayer.bot.chat import ChatQueue, parse_chat_json, split_message
from pyflayer.errors import KickedError
from pyflayer.events import (
    ChatEvent,
    DeathEvent,
    JoinEvent,
    KickEvent,
    RespawnEvent,
)
from pyflayer.testing import FakeServer


async def _start_bot(server: FakeServer, **kwargs: object) -> Bot:
    bot = Bot("Steve", host="127.0.0.1", port=server.port, use_srv=False, **kwargs)
    await bot.connect()
    return bot


async def _stop(bot: Bot, task: asyncio.Task[None]) -> None:
    await bot.close()
    await asyncio.gather(task, return_exceptions=True)


async def test_join_spawn_and_settings() -> None:
    async with FakeServer() as server:
        bot = await _start_bot(server)
        assert bot.joined
        assert bot.entity_id == 1
        assert bot.game_mode == 1
        task = asyncio.create_task(bot.run())
        await asyncio.sleep(0.05)
        assert bot.spawned
        assert server.settings is not None
        assert server.settings["locale"] == "en_US"
        await _stop(bot, task)


async def test_chat_roundtrip_and_event() -> None:
    async with FakeServer() as server:
        bot = await _start_bot(server)
        received: list[ChatEvent] = []
        bot.events.subscribe(ChatEvent, received.append)
        task = asyncio.create_task(bot.run())
        await bot.chat("hello world")
        async with asyncio.timeout(2):
            while not received:
                await asyncio.sleep(0.01)
        assert received[0].message.content == "<Steve> hello world"
        assert server.chats == ["hello world"]
        await _stop(bot, task)


async def test_keep_alive_is_answered() -> None:
    async with FakeServer() as server:
        bot = await _start_bot(server)
        task = asyncio.create_task(bot.run())
        server.send_play("keep_alive", {"keepAliveId": 1234})
        async with asyncio.timeout(2):
            while 1234 not in server.keep_alives:
                await asyncio.sleep(0.01)
        await _stop(bot, task)


async def test_death_triggers_respawn() -> None:
    async with FakeServer() as server:
        bot = await _start_bot(server)
        task = asyncio.create_task(bot.run())
        deaths: list[DeathEvent] = []
        bot.events.subscribe(DeathEvent, deaths.append)
        waiter = asyncio.create_task(bot.wait_for(RespawnEvent, timeout=2))
        server.send_play(
            "update_health", {"health": 0.0, "food": 20, "foodSaturation": 5.0}
        )
        await waiter
        assert deaths and deaths[0].health == 0
        assert not bot.dead
        await _stop(bot, task)


async def test_kick_raises_kicked_error() -> None:
    async with FakeServer(
        kick_after_join=True, kick_reason='{"text":"go away"}'
    ) as server:
        bot = await _start_bot(server)
        kicks: list[KickEvent] = []
        bot.events.subscribe(KickEvent, kicks.append)
        with pytest.raises(KickedError):
            await bot.run()
        assert kicks and kicks[0].reason_text == "go away"
        await bot.close()


async def test_bot_event_decorator() -> None:
    bot = Bot("Steve", host="127.0.0.1")
    seen: list[JoinEvent] = []

    @bot.event
    async def on_join(event: JoinEvent) -> None:
        seen.append(event)

    with pytest.raises(ValueError):
        @bot.event
        async def on_nope(event: object) -> None:
            pass

    bot.events.dispatch(JoinEvent(1, 0, 0, 0, 20, "flat"))
    await asyncio.sleep(0.01)
    assert len(seen) == 1
    await bot.events.aclose()


async def test_chat_queue_token_bucket_and_command_safety() -> None:
    clock = FakeClock()
    sent: list[str] = []

    async def send(message: str) -> None:
        sent.append(message)

    queue = ChatQueue(send, clock=clock, per=1.0, burst=2)
    await queue.send("/hello")
    await queue.send("world")
    assert sent == ["hello", "world"]

    third = asyncio.create_task(queue.send("third"))
    await asyncio.sleep(0)
    assert sent == ["hello", "world"]
    await clock.advance_async(1.0)
    await third
    assert sent == ["hello", "world", "third"]

    commands: list[str] = []

    async def send_command(message: str) -> None:
        commands.append(message)

    command_queue = ChatQueue(send_command, clock=clock)
    await command_queue.send("/register password password", allow_commands=True)
    assert commands == ["/register password password"]


def test_parse_chat_json_plain_text() -> None:
    message = parse_chat_json('{"text":"hello"}', 0)
    assert message.content == "hello"
    assert message.sender is None
    assert message.position == "chat"
    assert not message.is_whisper


def test_parse_chat_json_unwraps_player_chat() -> None:
    raw = '{"translate":"chat.type.text","with":[{"text":"[VIP] Steve"},{"text":"hi"}]}'
    message = parse_chat_json(raw, 0)
    assert message.sender == "[VIP] Steve"
    assert message.content == "hi"


def test_parse_chat_json_whisper_and_action_bar() -> None:
    raw = (
        '{"translate":"commands.message.display.incoming",'
        '"with":[{"text":"Steve"},{"text":"psst"}]}'
    )
    message = parse_chat_json(raw, 2)
    assert message.is_whisper
    assert message.position == "action_bar"
    assert message.content == "psst"


def test_parse_chat_json_malformed_degrades() -> None:
    message = parse_chat_json("not json", 1)
    assert message.content == "not json"
    assert message.position == "system"


def test_split_message() -> None:
    assert split_message("short") == ["short"]
    parts = split_message("x" * 600)
    assert all(len(part) <= 256 for part in parts)
    assert "".join(parts) == "x" * 600


async def test_player_info_ignores_unknown_updates_and_parses_display_name() -> None:
    """Regression: proxies send update_* for players never added; displayName is a chat payload."""
    from pyflayer.protocol.protodef import Packet

    bot = Bot("Steve", host="localhost", use_srv=False)
    uuid = "00000000-0000-0000-0000-000000000001"
    await bot._on_player_info(
        Packet(
            "player_info",
            {"action": "update_latency", "data": [{"uuid": uuid, "ping": 20}]},
            "play",
            "toClient",
        )
    )
    assert uuid not in bot.players

    await bot._on_player_info(
        Packet(
            "player_info",
            {
                "action": "add_player",
                "data": [
                    {
                        "uuid": uuid,
                        "name": "Alex",
                        "ping": 5,
                        "gamemode": 0,
                        "displayName": '{"text": "[VIP] Alex", "color": "gold"}',
                    }
                ],
            },
            "play",
            "toClient",
        )
    )
    info = bot.players[uuid]
    assert info.name == "Alex"
    assert info.display_name == "[VIP] Alex"
    assert info.game_mode == 0

    other = "00000000-0000-0000-0000-000000000002"
    await bot._on_player_info(
        Packet(
            "player_info",
            {
                "action": "add_player",
                "data": [
                    {"uuid": other, "name": "Bob", "ping": 1, "gamemode": 0, "displayName": None}
                ],
            },
            "play",
            "toClient",
        )
    )
    assert bot.players[other].display_name == "Bob"
