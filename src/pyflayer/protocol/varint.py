"""VarInt and VarLong codecs.

Minecraft VarInts are signed 32-bit values encoded in 7-bit groups, LSB first. Negative values use
two's complement and therefore always occupy 5 bytes (``-1`` is ``ff ff ff ff 0f``). VarLong is the
same idea with 64 bits / 10 bytes.

Over-long encodings (a 6th VarInt byte or a 10th VarLong byte with continuation) raise
:class:`~pyflayer.errors.MalformedPacket`.
"""

from __future__ import annotations

from typing import BinaryIO

from pyflayer.errors import ConnectionClosed, MalformedPacket

__all__ = [
    "encode_varint",
    "decode_varint",
    "encode_varlong",
    "decode_varlong",
    "read_varint",
    "read_varlong",
    "read_varint_sync",
    "read_varlong_sync",
]

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF


def _encode_unsigned(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_varint(value: int) -> bytes:
    """Encode a signed 32-bit integer as a VarInt."""
    if not -(2**31) <= value < 2**31:
        raise ValueError("VarInt out of range")
    return _encode_unsigned(value & _MASK32)


def encode_varlong(value: int) -> bytes:
    """Encode a signed 64-bit integer as a VarLong."""
    if not -(2**63) <= value < 2**63:
        raise ValueError("VarLong out of range")
    return _encode_unsigned(value & _MASK64)


def decode_varint(data: bytes | bytearray | memoryview, offset: int = 0) -> tuple[int, int]:
    """Decode a VarInt from ``data``.

    Returns:
        ``(value, bytes_consumed)``.

    Raises:
        MalformedPacket: If the encoding is truncated or longer than 5 bytes.
    """
    view = memoryview(data)
    result = 0
    for i in range(5):
        if offset + i >= len(view):
            raise MalformedPacket("truncated VarInt", offset=offset + i)
        byte = view[offset + i]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            value = result & _MASK32
            if value & 0x80000000:
                value -= 0x100000000
            return value, i + 1
    raise MalformedPacket("VarInt exceeds 5 bytes", offset=offset)


def decode_varlong(data: bytes | bytearray | memoryview, offset: int = 0) -> tuple[int, int]:
    """Decode a VarLong from ``data``. Returns ``(value, bytes_consumed)``."""
    view = memoryview(data)
    result = 0
    for i in range(10):
        if offset + i >= len(view):
            raise MalformedPacket("truncated VarLong", offset=offset + i)
        byte = view[offset + i]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            value = result & _MASK64
            if value & 0x8000000000000000:
                value -= 0x10000000000000000
            return value, i + 1
    raise MalformedPacket("VarLong exceeds 10 bytes", offset=offset)


async def read_varint(reader: object) -> int:
    """Read a VarInt from an :class:`asyncio.StreamReader`-like object, one byte at a time."""
    return await _read_async(reader, 5, "VarInt")


async def read_varlong(reader: object) -> int:
    """Read a VarLong from a stream, one byte at a time."""
    return await _read_async(reader, 10, "VarLong")


async def _read_async(reader: object, max_bytes: int, name: str) -> int:
    readexactly = getattr(reader, "readexactly")
    result = 0
    for i in range(max_bytes):
        try:
            chunk = await readexactly(1)
        except Exception as exc:  # asyncio.IncompleteReadError is not a PyFlayerError
            if exc.__class__.__name__ == "IncompleteReadError":
                raise ConnectionClosed(f"connection closed mid-{name}", bytes_consumed=i) from exc
            raise
        byte = chunk[0]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            bits = 32 if max_bytes == 5 else 64
            value = result & ((1 << bits) - 1)
            if value & (1 << (bits - 1)):
                value -= 1 << bits
            return value
    raise MalformedPacket(f"{name} exceeds {max_bytes} bytes")


def read_varint_sync(stream: BinaryIO) -> int:
    """Read a VarInt from a blocking binary stream (tools only; never on the event loop)."""
    result = 0
    for i in range(5):
        raw = stream.read(1)
        if not raw:
            raise ConnectionClosed("stream ended mid-VarInt", bytes_consumed=i)
        byte = raw[0]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            value = result & _MASK32
            if value & 0x80000000:
                value -= 0x100000000
            return value
    raise MalformedPacket("VarInt exceeds 5 bytes")


def read_varlong_sync(stream: BinaryIO) -> int:
    """Read a VarLong from a blocking binary stream (tools only)."""
    result = 0
    for i in range(10):
        raw = stream.read(1)
        if not raw:
            raise ConnectionClosed("stream ended mid-VarLong", bytes_consumed=i)
        byte = raw[0]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            value = result & _MASK64
            if value & 0x8000000000000000:
                value -= 0x10000000000000000
            return value
    raise MalformedPacket("VarLong exceeds 10 bytes")
