"""Named Binary Tag (NBT) reader/writer.

Two wire forms are supported:

* **Named root** - the classic form (1.8.9 through 1.20.1): tag type, root name, payload.
* **Nameless root** - the network form since protocol 764 / 1.20.2: tag type, payload.

The Python mapping is explicit rather than stringly-typed:

============================  ==========================================
TAG                           Python
============================  ==========================================
Byte / Short / Int / Long     ``int``
Float / Double                ``float``
String                        ``str``
ByteArray                     ``bytes``
IntArray / LongArray          ``tuple[int, ...]``
List                          :class:`NBTList` (keeps the element tag type)
Compound                      ``dict[str, object]``
============================  ==========================================

Strings are decoded as standard UTF-8, not Java's Modified UTF-8; lone surrogates are therefore
rejected. This is documented in ``docs/modules/protocol.md`` and matches what vanilla servers send
in practice.

Examples:
    >>> data = write_named_nbt("", {"Level": 1, "Name": "test"})
    >>> result = read_named_nbt(PacketReader(data))
    >>> result.value["Name"]
    'test'
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Protocol, Self

from pyflayer.errors import MalformedPacket

__all__ = [
    "TAG_BYTE",
    "TAG_BYTE_ARRAY",
    "TAG_COMPOUND",
    "TAG_DOUBLE",
    "TAG_END",
    "TAG_FLOAT",
    "TAG_INT",
    "TAG_INT_ARRAY",
    "TAG_LIST",
    "TAG_LONG",
    "TAG_LONG_ARRAY",
    "TAG_SHORT",
    "TAG_STRING",
    "NBTList",
    "NBTNamed",
    "NBTReader",
    "read_named_nbt",
    "read_nbt",
    "read_unnamed_nbt",
    "write_named_nbt",
    "write_nbt",
    "write_unnamed_nbt",
]

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

MAX_DEPTH = 512
MAX_STRING_CHARS = 32767


class NBTReader(Protocol):
    """Minimal reader surface required by the NBT decoder."""

    def read_u8(self) -> int: ...
    def read_u16(self) -> int: ...
    def read_i32(self) -> int: ...
    def read_i64(self) -> int: ...
    def read_f32(self) -> float: ...
    def read_f64(self) -> float: ...
    def read_bytes(self, count: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class NBTList:
    """A homogeneous NBT list. ``tag_type == TAG_END`` represents an empty list."""

    tag_type: int
    items: tuple[object, ...] = ()

    @classmethod
    def of(cls, items: list[object] | tuple[object, ...]) -> Self:
        """Build a list whose element type is inferred from the first item."""
        items = tuple(items)
        return cls(_tag_for_value(items[0]) if items else TAG_END, items)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)


@dataclass(frozen=True, slots=True)
class NBTNamed:
    """A named root tag (classic file and pre-1.20.2 network form)."""

    name: str
    value: object


def _tag_for_value(value: object) -> int:
    if isinstance(value, bool):
        return TAG_BYTE
    if isinstance(value, int):
        if -(2**31) <= value < 2**31:
            return TAG_INT
        return TAG_LONG
    if isinstance(value, float):
        return TAG_DOUBLE
    if isinstance(value, str):
        return TAG_STRING
    if isinstance(value, (bytes, bytearray)):
        return TAG_BYTE_ARRAY
    if isinstance(value, NBTList):
        return TAG_LIST
    if isinstance(value, dict):
        return TAG_COMPOUND
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, int) and -(2**31) <= item < 2**31 for item in value):
            return TAG_INT_ARRAY
        if all(isinstance(item, int) for item in value):
            return TAG_LONG_ARRAY
        return TAG_LIST
    raise TypeError(f"cannot infer NBT tag for {type(value).__name__}")


def _read_string(reader: NBTReader) -> str:
    length = reader.read_u16()
    if length > MAX_STRING_CHARS * 4:
        raise MalformedPacket("NBT string length exceeds limit", offset=None, length=length)
    raw = reader.read_bytes(length)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedPacket("invalid UTF-8 in NBT string", offset=exc.start) from exc


def _read_payload(reader: NBTReader, tag: int, depth: int) -> object:
    if depth > MAX_DEPTH:
        raise MalformedPacket("NBT depth limit exceeded", depth=depth)
    if tag == TAG_BYTE:
        value = reader.read_u8()
        return value - 256 if value & 0x80 else value
    if tag == TAG_SHORT:
        raw = reader.read_u16()
        return raw - 65536 if raw & 0x8000 else raw
    if tag == TAG_INT:
        return reader.read_i32()
    if tag == TAG_LONG:
        return reader.read_i64()
    if tag == TAG_FLOAT:
        return reader.read_f32()
    if tag == TAG_DOUBLE:
        return reader.read_f64()
    if tag == TAG_BYTE_ARRAY:
        length = reader.read_i32()
        if length < 0:
            raise MalformedPacket("negative NBT byte-array length", length=length)
        return reader.read_bytes(length)
    if tag == TAG_STRING:
        return _read_string(reader)
    if tag == TAG_LIST:
        element = reader.read_u8()
        length = reader.read_i32()
        if length < 0:
            raise MalformedPacket("negative NBT list length", length=length)
        if element == TAG_END and length > 0:
            raise MalformedPacket("NBT list of TAG_End with non-zero length", length=length)
        items = tuple(_read_payload(reader, element, depth + 1) for _ in range(length))
        return NBTList(element, items)
    if tag == TAG_COMPOUND:
        compound: dict[str, object] = {}
        while True:
            child = reader.read_u8()
            if child == TAG_END:
                return compound
            if child > TAG_LONG_ARRAY:
                raise MalformedPacket("unknown NBT tag type", tag=child)
            name = _read_string(reader)
            compound[name] = _read_payload(reader, child, depth + 1)
    if tag == TAG_INT_ARRAY:
        length = reader.read_i32()
        if length < 0:
            raise MalformedPacket("negative NBT int-array length", length=length)
        return tuple(reader.read_i32() for _ in range(length))
    if tag == TAG_LONG_ARRAY:
        length = reader.read_i32()
        if length < 0:
            raise MalformedPacket("negative NBT long-array length", length=length)
        return tuple(reader.read_i64() for _ in range(length))
    raise MalformedPacket("unknown NBT tag type", tag=tag)


def read_named_nbt(reader: NBTReader, *, max_depth: int = MAX_DEPTH) -> NBTNamed:
    """Read a classic named-root NBT document."""
    tag = reader.read_u8()
    if tag == TAG_END:
        return NBTNamed("", {})
    if tag > TAG_LONG_ARRAY:
        raise MalformedPacket("unknown NBT root tag", tag=tag)
    name = _read_string(reader)
    value = _read_payload(reader, tag, 0)
    return NBTNamed(name, value)


def read_unnamed_nbt(reader: NBTReader, *, max_depth: int = MAX_DEPTH) -> object:
    """Read a nameless-root network NBT document (1.20.2+)."""
    tag = reader.read_u8()
    if tag == TAG_END:
        return {}
    if tag > TAG_LONG_ARRAY:
        raise MalformedPacket("unknown NBT root tag", tag=tag)
    return _read_payload(reader, tag, 0)


def read_nbt(reader: NBTReader, *, named: bool = True) -> NBTNamed | object:
    """Read NBT in either form. Returns :class:`NBTNamed` when ``named`` is true."""
    return read_named_nbt(reader) if named else read_unnamed_nbt(reader)


# --------------------------------------------------------------------------- writer


class _Writer:
    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def u8(self, value: int) -> None:
        self.buf += struct.pack(">B", value & 0xFF)

    def u16(self, value: int) -> None:
        self.buf += struct.pack(">H", value & 0xFFFF)

    def i32(self, value: int) -> None:
        self.buf += struct.pack(">i", value)

    def i64(self, value: int) -> None:
        self.buf += struct.pack(">q", value)

    def f32(self, value: float) -> None:
        self.buf += struct.pack(">f", value)

    def f64(self, value: float) -> None:
        self.buf += struct.pack(">d", value)

    def string(self, value: str) -> None:
        raw = value.encode("utf-8")
        if len(raw) > 65535:
            raise MalformedPacket("NBT string too long to encode", length=len(raw))
        self.u16(len(raw))
        self.buf += raw

    def payload(self, tag: int, value: object, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise MalformedPacket("NBT depth limit exceeded", depth=depth)
        if tag == TAG_BYTE:
            if not isinstance(value, int):
                raise TypeError("NBT byte must be int")
            self.u8(value)
        elif tag == TAG_SHORT:
            if not isinstance(value, int):
                raise TypeError("NBT short must be int")
            self.u16(value)
        elif tag == TAG_INT:
            if not isinstance(value, int):
                raise TypeError("NBT int must be int")
            self.i32(value)
        elif tag == TAG_LONG:
            if not isinstance(value, int):
                raise TypeError("NBT long must be int")
            self.i64(value)
        elif tag == TAG_FLOAT:
            if not isinstance(value, (int, float)):
                raise TypeError("NBT float must be a number")
            self.f32(float(value))
        elif tag == TAG_DOUBLE:
            if not isinstance(value, (int, float)):
                raise TypeError("NBT double must be a number")
            self.f64(float(value))
        elif tag == TAG_BYTE_ARRAY:
            raw = bytes(value)  # type: ignore[arg-type]
            self.i32(len(raw))
            self.buf += raw
        elif tag == TAG_STRING:
            if not isinstance(value, str):
                raise TypeError("NBT string must be str")
            self.string(value)
        elif tag == TAG_LIST:
            tag_type, items = _coerce_list(value)
            self.u8(tag_type)
            self.i32(len(items))
            for item in items:
                self.payload(tag_type, item, depth + 1)
        elif tag == TAG_COMPOUND:
            if not isinstance(value, dict):
                raise TypeError("NBT compound must be a dict")
            for key, child in value.items():
                if not isinstance(key, str):
                    raise TypeError("NBT compound keys must be str")
                child_tag = _tag_for_value(child)
                self.u8(child_tag)
                self.string(key)
                self.payload(child_tag, child, depth + 1)
            self.u8(TAG_END)
        elif tag == TAG_INT_ARRAY:
            items = tuple(value)  # type: ignore[arg-type]
            self.i32(len(items))
            for item in items:
                self.i32(int(item))
        elif tag == TAG_LONG_ARRAY:
            items = tuple(value)  # type: ignore[arg-type]
            self.i32(len(items))
            for item in items:
                self.i64(int(item))
        else:
            raise MalformedPacket("unknown NBT tag type", tag=tag)

    def root(self, tag: int, value: object, name: str | None) -> bytes:
        self.u8(tag)
        if name is not None:
            self.string(name)
        self.payload(tag, value)
        return bytes(self.buf)


def _coerce_list(value: object) -> tuple[int, tuple[object, ...]]:
    if isinstance(value, NBTList):
        tag_type = value.tag_type
        items = value.items
        if tag_type == TAG_END and items:
            tag_type = _tag_for_value(items[0])
        return tag_type, tuple(items)
    if isinstance(value, (list, tuple)):
        items = tuple(value)
        return (_tag_for_value(items[0]) if items else TAG_END), items
    raise TypeError("NBT list must be a list/tuple/NBTList")


def write_unnamed_nbt(value: object) -> bytes:
    """Encode a nameless-root NBT document."""
    tag = _tag_for_value(value)
    return _Writer().root(tag, value, None)


def write_named_nbt(name: str, value: object) -> bytes:
    """Encode a classic named-root NBT document."""
    tag = _tag_for_value(value)
    return _Writer().root(tag, value, name)


def write_nbt(value: object, *, named: bool = True, name: str = "") -> bytes:
    """Encode NBT in either form."""
    return write_named_nbt(name, value) if named else write_unnamed_nbt(value)


def is_finite_float(value: float) -> bool:
    """NBT floats should not be NaN/Inf; helper for validating user data."""
    return math.isfinite(value)
