from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from pyflayer.data.loader import McData
from pyflayer.errors import ConnectionClosed, LoginRejected, ProtocolError
from pyflayer.models.enums import ConnectionState
from pyflayer.protocol.client import ProtocolClient
from pyflayer.protocol.protodef import Packet
from pyflayer.protocol.registry import PacketRegistry
from pyflayer.testing import FakeServer


async def _read_until(client: ProtocolClient, name: str, *, timeout_seconds: float = 3.0) -> object:
    async with asyncio.timeout(timeout_seconds):
        async for packet in client.packets():
            if packet.name == name:
                return packet
    raise AssertionError(f"did not receive {name}")


async def test_connect_without_encryption_or_compression() -> None:
    async with FakeServer() as server:
        client = ProtocolClient("127.0.0.1", "Steve", port=server.port, use_srv=False)
        session = await client.connect()
        assert session.username == "Steve"
        assert client.state.state is ConnectionState.PLAY
        assert client.state.history[:3] == (
            ConnectionState.HANDSHAKING,
            ConnectionState.LOGIN,
            ConnectionState.PLAY,
        )
        assert not client.encrypted
        assert client.compression_threshold == -1
        join = await _read_until(client, "login")
        assert join.fields["entityId"] == 1
        await client.send_chat("hello")
        echo = await _read_until(client, "chat")
        assert json.loads(echo.fields["message"]) == {"text": "<Steve> hello"}
        await client.close()
        assert client.state.closed


async def test_connect_with_encryption_and_compression() -> None:
    async with FakeServer(encryption=True, compression=64) as server:
        client = ProtocolClient("127.0.0.1", "Alex", port=server.port, use_srv=False)
        await client.connect()
        assert client.encrypted
        assert client.compression_threshold == 64
        await _read_until(client, "position")
        await client.send_chat("compressed and encrypted")
        echo = await _read_until(client, "chat")
        assert "compressed and encrypted" in echo.fields["message"]
        await client.close()


@pytest.mark.parametrize("use_compression", [True, False])
async def test_server_compression_transition_is_mandatory(use_compression: bool) -> None:
    async with FakeServer(compression=1) as server:
        client = ProtocolClient(
            "127.0.0.1",
            "Steve",
            port=server.port,
            use_srv=False,
            use_compression=use_compression,
        )
        await client.connect()
        assert client.compression_threshold == 1
        await _read_until(client, "position")
        await client.send_chat("compression transition")
        echo = await _read_until(client, "chat")
        assert "compression transition" in echo.fields["message"]
        await client.close()


async def test_login_rejected() -> None:
    async with FakeServer(reject_login='{"text":"you are not allowed"}') as server:
        client = ProtocolClient("127.0.0.1", "Steve", port=server.port, use_srv=False)
        with pytest.raises(LoginRejected) as info:
            await client.connect()
        assert info.value.fields["reason"].plain_text() == "you are not allowed"
        # A failed login closes its socket rather than leaving a half-open connection.
        assert client.connection is None
        await client.close()
        assert client.state.closed


async def test_send_packet_outside_play_raises() -> None:
    client = ProtocolClient("127.0.0.1", "Steve", use_srv=False)
    with pytest.raises(ProtocolError):
        await client.send_packet("chat", {"message": "hi"})


async def test_packets_skips_unknown_placeholders() -> None:
    class Client(ProtocolClient):
        def __init__(self) -> None:
            super().__init__("127.0.0.1", "Steve", use_srv=False)
            self.state.transition(ConnectionState.LOGIN)
            self.state.transition(ConnectionState.PLAY)
            self.pending = [
                Packet(name="unknown_0x7f", fields={}, state="play", direction="toClient"),
                Packet(name="unsupported_chunk", fields={}, state="play", direction="toClient"),
                Packet(name="chat", fields={}, state="play", direction="toClient"),
            ]

        async def read_packet(self) -> Packet:
            if not self.pending:
                raise ConnectionClosed("done")
            return self.pending.pop(0)

    client = Client()
    names: list[str] = []
    with pytest.raises(ConnectionClosed):
        async for packet in client.packets():
            names.append(packet.name)
    assert names == ["chat"]


def test_player_info_relative_switch_decodes() -> None:
    mc = McData.load("1.8.9")
    registry = PacketRegistry(mc)
    player_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    payload = registry.encode(
        "play",
        "toClient",
        "player_info",
        {
            "action": "add_player",
            "data": [
                {
                    "uuid": player_id,
                    "name": "Steve",
                    "properties": [],
                    "gamemode": 1,
                    "ping": 42,
                    "displayName": None,
                }
            ],
        },
    )
    packet = registry.decode("play", "toClient", payload)
    assert packet.name == "player_info"
    assert packet.fields["action"] == "add_player"
    entry = packet.fields["data"][0]
    assert entry["name"] == "Steve"
    assert entry["gamemode"] == 1
    assert entry["ping"] == 42
