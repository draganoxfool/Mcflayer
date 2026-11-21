"""BitSets: a VarInt count of big-endian 64-bit longs."""

from __future__ import annotations

__all__ = ["read_bitset", "write_bitset"]


def read_bitset(reader: object, *, max_longs: int = 1024) -> tuple[int, ...]:
    """Read a BitSet as a tuple of longs."""
    count = reader.read_varint()  # type: ignore[attr-defined]
    if count < 0 or count > max_longs:
        from pyflayer.errors import MalformedPacket

        raise MalformedPacket("BitSet length out of range", length=count)
    return tuple(reader.read_i64() for _ in range(count))  # type: ignore[attr-defined]


def write_bitset(values: tuple[int, ...] | list[int], writer: object) -> None:
    """Write a BitSet to a writer with ``write_varint``/``write_i64``."""
    writer.write_varint(len(values))  # type: ignore[attr-defined]
    for value in values:
        writer.write_i64(value)  # type: ignore[attr-defined]
