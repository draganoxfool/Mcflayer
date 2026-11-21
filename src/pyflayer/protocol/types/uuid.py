"""UUID encoding (two big-endian unsigned 64-bit integers)."""

from __future__ import annotations

import uuid as _uuid

from pyflayer.errors import MalformedPacket

__all__ = ["read_uuid", "uuid_from_int", "uuid_to_int", "write_uuid"]


def read_uuid(reader: object) -> _uuid.UUID:
    """Read a 16-byte UUID from a reader with ``read_bytes``."""
    raw = reader.read_bytes(16)  # type: ignore[attr-defined]
    return _uuid.UUID(bytes=raw)


def write_uuid(value: _uuid.UUID) -> bytes:
    """Return the 16 wire bytes of a UUID."""
    return value.bytes


def uuid_from_int(msb: int, lsb: int) -> _uuid.UUID:
    """Build a UUID from its two signed 64-bit halves."""
    return _uuid.UUID(int=((msb & 0xFFFFFFFFFFFFFFFF) << 64) | (lsb & 0xFFFFFFFFFFFFFFFF))


def uuid_to_int(value: _uuid.UUID) -> tuple[int, int]:
    """Split a UUID into signed 64-bit halves as sent on the wire."""
    raw = value.int
    msb = (raw >> 64) & 0xFFFFFFFFFFFFFFFF
    lsb = raw & 0xFFFFFFFFFFFFFFFF
    if msb & 0x8000000000000000:
        msb -= 1 << 64
    if lsb & 0x8000000000000000:
        lsb -= 1 << 64
    return msb, lsb


def parse_uuid(text: str) -> _uuid.UUID:
    """Parse a UUID string, raising a protocol error on bad input."""
    try:
        return _uuid.UUID(text)
    except ValueError as exc:
        raise MalformedPacket("invalid UUID", value=text) from exc
