from __future__ import annotations

import asyncio
import json

import pytest

from pyflayer.errors import MalformedPacket, ProtocolError
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.framing import FrameCodec, read_frame_async, write_frame_async
from pyflayer.protocol.status import parse_status_json, ping

STATUS_JSON = {
    "version": {"name": "1.8.9", "protocol": 47},
    "players": {"max": 20, "online": 1, "sample": [{"name": "Steve", "id": "x"}]},
    "description": {"text": "A ", "extra": [{"text": "Server"}]},
    "favicon": "data:image/png;base64," + "aGVsbG8=",
}


async def _fake_status_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    codec = FrameCodec()
    try:
        handshake = PacketReader(await read_frame_async(reader, codec))
        assert handshake.read_varint() == 0
        assert handshake.read_varint() == 47
        host = handshake.read_string()
        port = handshake.read_u16()
        assert handshake.read_varint() == 1
        assert host == "127.0.0.1"
        assert port > 0

        request = PacketReader(await read_frame_async(reader, codec))
        assert request.read_varint() == 0

        reply = PacketWriter()
        reply.write_varint(0)
        reply.write_string(json.dumps(STATUS_JSON))
        await write_frame_async(writer, reply.to_bytes(), codec)

        ping_packet = PacketReader(await read_frame_async(reader, codec))
        assert ping_packet.read_varint() == 1
        token = ping_packet.read_i64()
        pong = PacketWriter()
        pong.write_varint(1)
        pong.write_i64(token)
        await write_frame_async(writer, pong.to_bytes(), codec)
    finally:
        writer.close()
        await writer.wait_closed()


async def test_ping_roundtrip() -> None:
    server = await asyncio.start_server(_fake_status_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        status = await ping("127.0.0.1", port, use_srv=False, timeout=5.0)
    finally:
        server.close()
        await server.wait_closed()
    assert status.version_name == "1.8.9"
    assert status.protocol == 47
    assert status.online_players == 1
    assert status.max_players == 20
    assert status.motd == "A Server"
    assert status.sample[0].name == "Steve"
    assert status.favicon_png == b"hello"
    assert status.latency_ms >= 0


async def test_ping_bad_packet_id() -> None:
    async def server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        codec = FrameCodec()
        await read_frame_async(reader, codec)
        await read_frame_async(reader, codec)
        reply = PacketWriter()
        reply.write_varint(2)
        await write_frame_async(writer, reply.to_bytes(), codec)
        writer.close()

    server_obj = await asyncio.start_server(server, "127.0.0.1", 0)
    port = server_obj.sockets[0].getsockname()[1]
    try:
        with pytest.raises(ProtocolError):
            await ping("127.0.0.1", port, use_srv=False, timeout=5.0)
    finally:
        server_obj.close()
        await server_obj.wait_closed()


def test_parse_status_malformed() -> None:
    with pytest.raises(MalformedPacket):
        parse_status_json("not json")
    with pytest.raises(MalformedPacket):
        parse_status_json("[]")


def test_parse_status_tolerates_optional_fields() -> None:
    status = parse_status_json('{"version":{"name":"x"},"players":{},"description":"hi"}')
    assert status.protocol == 0
    assert status.max_players == 0
    assert status.motd == "hi"
    assert status.favicon_png is None


def test_parse_status_tolerates_malformed_numbers() -> None:
    status = parse_status_json(
        '{"version":{"name":null,"protocol":"many"},'
        '"players":{"max":"lots","online":null},"description":"hi"}'
    )
    assert status.version_name == "unknown"
    assert status.protocol == 0
    assert status.max_players == 0
    assert status.online_players == 0
