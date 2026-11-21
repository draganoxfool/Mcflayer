from __future__ import annotations

import asyncio

import pytest

from pyflayer.errors import ConnectionClosed, MalformedPacket
from pyflayer.protocol.varint import (
    decode_varint,
    decode_varlong,
    encode_varint,
    encode_varlong,
    read_varint,
)


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (0, b"\x00"),
        (1, b"\x01"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (255, b"\xff\x01"),
        (2097151, b"\xff\xff\x7f"),
        (2147483647, b"\xff\xff\xff\xff\x07"),
        (-1, b"\xff\xff\xff\xff\x0f"),
        (-2147483648, b"\x80\x80\x80\x80\x08"),
    ],
)
def test_varint_golden(value: int, encoded: bytes) -> None:
    assert encode_varint(value) == encoded
    assert decode_varint(encoded) == (value, len(encoded))


def test_varint_sixth_byte_rejected() -> None:
    with pytest.raises(MalformedPacket):
        decode_varint(b"\x80\x80\x80\x80\x80\x01")


def test_varint_truncated_rejected() -> None:
    with pytest.raises(MalformedPacket):
        decode_varint(b"\x80\x80")


def test_varint_out_of_range_encode() -> None:
    with pytest.raises(ValueError):
        encode_varint(2**31)


def test_varlong_roundtrip() -> None:
    for value in (0, 1, -1, 2**62, -(2**63), 2**63 - 1):
        encoded = encode_varlong(value)
        assert len(encoded) <= 10
        assert decode_varlong(encoded)[0] == value


def test_varlong_overlong_rejected() -> None:
    with pytest.raises(MalformedPacket):
        decode_varlong(b"\x80" * 10 + b"\x01")


class OneByteReader:
    """Simulates a TCP stream that delivers one byte per read."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._index = 0

    async def readexactly(self, count: int) -> bytes:
        if self._index + count > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._index :], count)
        chunk = self._data[self._index : self._index + count]
        self._index += count
        return chunk


async def test_streaming_varint_split_reads() -> None:
    reader = OneByteReader(encode_varint(-1234567))
    assert await read_varint(reader) == -1234567


async def test_streaming_varint_maps_incomplete_read() -> None:
    reader = OneByteReader(b"\x80")
    with pytest.raises(ConnectionClosed):
        await read_varint(reader)
