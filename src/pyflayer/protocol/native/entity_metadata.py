"""1.8 entity metadata codec (``entityMetadataLoop``).

The wire format is a sequence of entries terminated by ``0x7F``. Each header packs the value type in
the top three bits and the key in the bottom five::

    header = (type << 5) | key

Types are: 0 byte, 1 short, 2 int, 3 float, 4 string, 5 slot, 6 three ints, 7 three floats. Decoding
returns ``{key: value}``; writing infers the type from the Python value or accepts explicit
``(type, value)`` tuples.

Examples:
    >>> codec = EntityMetadataLoopCodec()
    >>> from pyflayer.protocol.buffer import PacketReader
    >>> codec.read(PacketReader(b"\\x7f"), {})
    {}
"""

from __future__ import annotations

from typing import Any

from pyflayer.models.items import ItemStack
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.types.slot import read_slot, write_slot

__all__ = ["METADATA_END", "EntityMetadataLoopCodec"]

METADATA_END = 0x7F

#: value type ids
BYTE, SHORT, INT, FLOAT, STRING, SLOT, VECTOR3I, VECTOR3F = range(8)


class EntityMetadataLoopCodec:
    """Codec for the named global type ``entityMetadataLoop``."""

    __slots__ = ()

    def read(self, reader: PacketReader, ctx: dict[str, Any]) -> dict[int, Any]:
        del ctx
        result: dict[int, Any] = {}
        while True:
            header = reader.read_u8()
            if header == METADATA_END:
                return result
            value_type = (header >> 5) & 0x07
            key = header & 0x1F
            result[key] = _read_value(reader, value_type)

    def write(self, writer: PacketWriter, value: Any, ctx: dict[str, Any]) -> None:
        del ctx
        entries = value.items() if isinstance(value, dict) else value
        for key, raw in entries:
            if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], int):
                value_type, item = raw
            else:
                value_type, item = _infer_type(raw)
            writer.write_u8((value_type << 5) | (int(key) & 0x1F))
            _write_value(writer, value_type, item)
        writer.write_u8(METADATA_END)


def _read_value(reader: PacketReader, value_type: int) -> Any:
    if value_type == BYTE:
        return reader.read_i8()
    if value_type == SHORT:
        return reader.read_i16()
    if value_type == INT:
        return reader.read_i32()
    if value_type == FLOAT:
        return reader.read_f32()
    if value_type == STRING:
        return reader.read_string(32767)
    if value_type == SLOT:
        return read_slot(reader, reader.features)
    if value_type == VECTOR3I:
        return (reader.read_i32(), reader.read_i32(), reader.read_i32())
    if value_type == VECTOR3F:
        return (reader.read_f32(), reader.read_f32(), reader.read_f32())
    raise ValueError(f"unknown entity metadata type {value_type}")


def _write_value(writer: PacketWriter, value_type: int, value: Any) -> None:
    if value_type == BYTE:
        writer.write_i8(int(value))
    elif value_type == SHORT:
        writer.write_i16(int(value))
    elif value_type == INT:
        writer.write_i32(int(value))
    elif value_type == FLOAT:
        writer.write_f32(float(value))
    elif value_type == STRING:
        if not isinstance(value, str):
            writer.write_string(str(value))
        else:
            writer.write_string(value)
    elif value_type == SLOT:
        write_slot(value, writer, writer.features)
    elif value_type == VECTOR3I:
        x, y, z = value
        writer.write_i32(int(x))
        writer.write_i32(int(y))
        writer.write_i32(int(z))
    elif value_type == VECTOR3F:
        x, y, z = value
        writer.write_f32(float(x))
        writer.write_f32(float(y))
        writer.write_f32(float(z))
    else:  # pragma: no cover - guarded by the writer
        raise ValueError(f"unknown entity metadata type {value_type}")


def _infer_type(value: Any) -> tuple[int, Any]:
    if isinstance(value, bool):
        return BYTE, int(value)
    if isinstance(value, int):
        return INT, value
    if isinstance(value, float):
        return FLOAT, value
    if isinstance(value, str):
        return STRING, value
    if isinstance(value, ItemStack):
        return SLOT, value
    if isinstance(value, tuple) and len(value) == 3:
        if all(isinstance(part, int) for part in value):
            return VECTOR3I, value
        if all(isinstance(part, (int, float)) for part in value):
            return VECTOR3F, value
    return STRING, str(value)
