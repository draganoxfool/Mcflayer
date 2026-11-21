from __future__ import annotations

import asyncio
import zlib

import pytest

from pyflayer.errors import CompressionError, ConnectionClosed, FramingError
from pyflayer.protocol.buffer import PacketWriter
from pyflayer.protocol.connection import Connection
from pyflayer.protocol.framing import (
    MAX_UNCOMPRESSED,
    FrameCodec,
    read_frame_async,
)
from pyflayer.protocol.varint import decode_varint, encode_varint


def payload(size: int = 10) -> bytes:
    return b"payload" + b"x" * max(0, size - 7)


def test_uncompressed_frame_roundtrip() -> None:
    codec = FrameCodec()
    frame = codec.encode(payload())
    length, consumed = decode_varint(frame)
    assert length == len(frame) - consumed
    assert codec.decode(frame[consumed:]) == payload()


def test_compression_threshold_boundaries() -> None:
    codec = FrameCodec(compression_threshold=8)
    small = b"1234567"
    frame = codec.encode(small)
    body = frame[len(encode_varint(len(frame) - 1)) :]
    declared, consumed = decode_varint(body)
    assert declared == 0
    assert body[consumed:] == small

    large = b"12345678"
    frame = codec.encode(large)
    body = frame[len(encode_varint(len(frame) - 1)) :]
    declared, consumed = decode_varint(body)
    assert declared == len(large)
    assert zlib.decompress(body[consumed:]) == large
    assert codec.decode(body) == large


def test_uncompressed_packet_at_threshold_rejected() -> None:
    codec = FrameCodec(compression_threshold=5)
    body = encode_varint(0) + b"12345"
    with pytest.raises(CompressionError):
        codec.decode(body)


def test_declared_length_larger_than_actual_rejected() -> None:
    codec = FrameCodec(compression_threshold=1)
    compressed = zlib.compress(b"hello")
    body = encode_varint(100) + compressed
    with pytest.raises(CompressionError):
        codec.decode(body)


def test_declared_length_smaller_than_actual_rejected() -> None:
    codec = FrameCodec(compression_threshold=1)
    compressed = zlib.compress(b"hello world" * 10)
    body = encode_varint(5) + compressed
    with pytest.raises(CompressionError):
        codec.decode(body)


def test_zlib_bomb_rejected_before_inflate() -> None:
    codec = FrameCodec(compression_threshold=1)
    body = encode_varint(MAX_UNCOMPRESSED + 1) + b"\x00" * 10
    with pytest.raises(CompressionError):
        codec.decode(body)


def test_invalid_zlib_rejected() -> None:
    codec = FrameCodec(compression_threshold=1)
    body = encode_varint(10) + b"not-zlib!!"
    with pytest.raises(CompressionError):
        codec.decode(body)


def test_frame_too_large() -> None:
    codec = FrameCodec(max_frame=5)
    with pytest.raises(FramingError):
        codec.encode(b"123456")


def test_zero_frame_length_rejected() -> None:
    async def run() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x00")
        reader.feed_eof()
        with pytest.raises(FramingError):
            await read_frame_async(reader, FrameCodec())

    asyncio.run(run())


async def test_adversarial_one_byte_reads() -> None:
    codec = FrameCodec(compression_threshold=-1)
    frame = codec.encode(payload(100))

    async def server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        for byte in frame:
            writer.write(bytes((byte,)))
            await writer.drain()
            await asyncio.sleep(0)
        writer.close()

    server_obj = await asyncio.start_server(server, "127.0.0.1", 0)
    port = server_obj.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert await read_frame_async(reader, codec) == payload(100)
        writer.close()
        await writer.wait_closed()
    finally:
        server_obj.close()
        await server_obj.wait_closed()


async def test_connection_read_timeout_is_not_reported_as_reset() -> None:
    reader = asyncio.StreamReader()
    connection = Connection(reader, None, read_timeout=0.01)  # type: ignore[arg-type]

    with pytest.raises(ConnectionClosed) as info:
        await connection.read_payload()
    assert "timed out" in str(info.value)


async def test_connection_closed_mid_frame() -> None:
    codec = FrameCodec()
    frame = codec.encode(payload())
    async def server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(frame[:3])
        await writer.drain()
        writer.close()

    server_obj = await asyncio.start_server(server, "127.0.0.1", 0)
    port = server_obj.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        with pytest.raises(FramingError):
            await read_frame_async(reader, codec)
        writer.close()
        await writer.wait_closed()
    finally:
        server_obj.close()
        await server_obj.wait_closed()
