"""Zero-copy-ish packet buffer primitives.

:class:`PacketReader` wraps a ``memoryview`` and exposes bounds-checked reads. :class:`PacketWriter`
builds bytes with a ``bytearray``. Both understand Minecraft's primitives: VarInt/VarLong, UTF-8
strings whose length prefix counts UTF-8 bytes (max 32767 characters), UUIDs, packed positions, NBT
and slots.

Examples:
    >>> w = PacketWriter()
    >>> w.write_varint(300)
    >>> w.write_string("hi")
    >>> r = PacketReader(w.to_bytes())
    >>> r.read_varint(), r.read_string()
    (300, 'hi')
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Any, TypeVar

from pyflayer.data.features import Features
from pyflayer.errors import MalformedPacket
from pyflayer.models.vec3 import BlockPos
from pyflayer.protocol.types.bitset import read_bitset, write_bitset
from pyflayer.protocol.types.nbt import NBTNamed, read_nbt, write_nbt
from pyflayer.protocol.types.position import pack_position, unpack_position
from pyflayer.protocol.types.slot import read_slot, write_slot
from pyflayer.protocol.types.uuid import read_uuid
from pyflayer.protocol.varint import decode_varint, decode_varlong, encode_varint, encode_varlong

__all__ = ["PacketReader", "PacketWriter"]

T = TypeVar("T")

DEFAULT_MAX_STRING_CHARS = 32767


class PacketReader:
    """Bounds-checked reader over a bytes-like packet payload."""

    __slots__ = ("_limit", "_offset", "_view", "features", "packet_name")

    def __init__(
        self,
        data: bytes | bytearray | memoryview,
        *,
        features: Features | None = None,
        packet_name: str | None = None,
    ) -> None:
        self._view = memoryview(data)
        self._offset = 0
        self._limit = len(self._view)
        self.features = features or Features.for_version("1.8.9")
        self.packet_name = packet_name

    # ------------------------------------------------------------------ state
    @property
    def offset(self) -> int:
        """Current read position."""
        return self._offset

    @property
    def remaining(self) -> int:
        """Bytes left to read."""
        return self._limit - self._offset

    def tell(self) -> int:
        """Current read position (protodef-friendly alias)."""
        return self._offset

    def __len__(self) -> int:
        return self._limit

    def _need(self, count: int) -> None:
        if count < 0 or self._offset + count > self._limit:
            raise MalformedPacket(
                "unexpected end of packet",
                offset=self._offset,
                needed=count,
                remaining=self.remaining,
                packet=self.packet_name,
            )

    def _unpack(self, fmt: str, size: int) -> Any:
        self._need(size)
        value = struct.unpack_from(fmt, self._view, self._offset)[0]
        self._offset += size
        return value

    # ------------------------------------------------------------------ raw
    def read_bytes(self, count: int) -> bytes:
        """Read exactly ``count`` bytes."""
        self._need(count)
        value = self._view[self._offset : self._offset + count].tobytes()
        self._offset += count
        return value

    def read_memoryview(self, count: int) -> memoryview:
        """Return a read-only view of the next ``count`` bytes without copying."""
        self._need(count)
        view = self._view[self._offset : self._offset + count]
        self._offset += count
        return view

    def read_remaining(self) -> bytes:
        """Read everything left."""
        return self.read_bytes(self.remaining)

    def skip(self, count: int) -> None:
        """Advance by ``count`` bytes."""
        self._need(count)
        self._offset += count

    def unread_bytes(self, data: bytes) -> None:
        """Push ``data`` back in front of the unread tail.

        Used by codecs that must inspect and mutate a byte before handing it to another codec
        (``topBitSetTerminatedArray`` clears the continuation bit on the first element byte).
        """
        tail = self._view[self._offset : self._limit].tobytes()
        self._view = memoryview(bytes(data) + tail)
        self._limit = len(self._view)
        self._offset = 0

    # ------------------------------------------------------------------ ints
    def read_u8(self) -> int:
        return int(self._unpack(">B", 1))

    def read_i8(self) -> int:
        return int(self._unpack(">b", 1))

    def read_u16(self) -> int:
        return int(self._unpack(">H", 2))

    def read_i16(self) -> int:
        return int(self._unpack(">h", 2))

    def read_u32(self) -> int:
        return int(self._unpack(">I", 4))

    def read_i32(self) -> int:
        return int(self._unpack(">i", 4))

    def read_u64(self) -> int:
        return int(self._unpack(">Q", 8))

    def read_i64(self) -> int:
        return int(self._unpack(">q", 8))

    def read_f32(self) -> float:
        return float(self._unpack(">f", 4))

    def read_f64(self) -> float:
        return float(self._unpack(">d", 8))

    def read_bool(self) -> bool:
        # Notchian clients read a byte and treat any non-zero value as true; some server
        # implementations and proxy plugins write values other than 0/1, so rejecting them here
        # disconnects otherwise valid sessions.
        return bool(self.read_u8())

    def read_varint(self) -> int:
        value, consumed = decode_varint(self._view, self._offset)
        self._offset += consumed
        return value

    def read_varlong(self) -> int:
        value, consumed = decode_varlong(self._view, self._offset)
        self._offset += consumed
        return value

    # ------------------------------------------------------------------ strings
    def read_string(self, max_chars: int = DEFAULT_MAX_STRING_CHARS) -> str:
        """Read a UTF-8 string whose prefix counts UTF-8 bytes."""
        length = self.read_varint()
        return self.read_string_bytes(length, max_chars=max_chars)

    def read_string_bytes(self, length: int, *, max_chars: int = DEFAULT_MAX_STRING_CHARS) -> str:
        """Read a UTF-8 string body after an already-decoded byte-length prefix."""
        if length < 0 or length > max_chars * 4:
            raise MalformedPacket(
                "string length out of range",
                length=length,
                max=max_chars,
                packet=self.packet_name,
            )
        raw = self.read_bytes(length)
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedPacket(
                "invalid UTF-8 in string", offset=self._offset - length + exc.start
            ) from exc
        if len(value) > max_chars:
            raise MalformedPacket(
                "string exceeds maximum character count",
                length=len(value),
                max=max_chars,
                packet=self.packet_name,
            )
        return value

    def read_string_units(self, length: int, *, max_chars: int = DEFAULT_MAX_STRING_CHARS) -> str:
        """Deprecated alias for :meth:`read_string_bytes` (protodef compatibility)."""
        return self.read_string_bytes(length, max_chars=max_chars)

    # ------------------------------------------------------------------ composites
    def read_uuid(self) -> object:
        return read_uuid(self)

    def read_position(self, *, packed_xzy: bool | None = None) -> BlockPos:
        value = self.read_u64()
        if packed_xzy is None:
            packed_xzy = self.features.position_packed_xzy
        return unpack_position(value, packed_xzy=packed_xzy)

    def read_nbt(self, *, named: bool | None = None) -> NBTNamed | object:
        if named is None:
            named = not self.features.network_nbt_nameless
        return read_nbt(self, named=named)

    def read_slot(self, features: Features | None = None) -> object:
        return read_slot(self, features or self.features)

    def read_bitset(self, *, max_longs: int = 1024) -> tuple[int, ...]:
        return read_bitset(self, max_longs=max_longs)

    def read_optional(self, reader: Callable[[], T]) -> T | None:
        """Read a protodef ``option`` (bool present flag, then value)."""
        return reader() if self.read_bool() else None

    def read_array(self, reader: Callable[[], T], count: int | None = None) -> list[T]:
        """Read ``count`` values, or a VarInt-prefixed array when ``count`` is None."""
        if count is None:
            count = self.read_varint()
        if count < 0:
            raise MalformedPacket("negative array length", length=count)
        return [reader() for _ in range(count)]

    def ensure_finished(self, *, strict: bool = True) -> None:
        """Verify every byte was consumed (strict mode is the default in tests)."""
        if strict and self.remaining:
            raise MalformedPacket(
                "trailing bytes after packet",
                offset=self._offset,
                remaining=self.remaining,
                packet=self.packet_name,
            )


class PacketWriter:
    """Builder for packet payloads."""

    __slots__ = ("_buf", "features")

    def __init__(self, *, features: Features | None = None) -> None:
        self._buf = bytearray()
        self.features = features or Features.for_version("1.8.9")

    def __len__(self) -> int:
        return len(self._buf)

    def to_bytes(self) -> bytes:
        """Return the accumulated payload."""
        return bytes(self._buf)

    def write_bytes(self, data: bytes | bytearray | memoryview) -> None:
        self._buf += data

    def write_u8(self, value: int) -> None:
        self._buf += struct.pack(">B", value & 0xFF)

    def write_i8(self, value: int) -> None:
        self._buf += struct.pack(">b", value)

    def write_u16(self, value: int) -> None:
        self._buf += struct.pack(">H", value & 0xFFFF)

    def write_i16(self, value: int) -> None:
        self._buf += struct.pack(">h", value)

    def write_u32(self, value: int) -> None:
        self._buf += struct.pack(">I", value & 0xFFFFFFFF)

    def write_i32(self, value: int) -> None:
        self._buf += struct.pack(">i", value)

    def write_u64(self, value: int) -> None:
        self._buf += struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF)

    def write_i64(self, value: int) -> None:
        self._buf += struct.pack(">q", value)

    def write_f32(self, value: float) -> None:
        self._buf += struct.pack(">f", value)

    def write_f64(self, value: float) -> None:
        self._buf += struct.pack(">d", value)

    def write_bool(self, value: bool) -> None:
        self.write_u8(1 if value else 0)

    def write_varint(self, value: int) -> None:
        self._buf += encode_varint(value)

    def write_varlong(self, value: int) -> None:
        self._buf += encode_varlong(value)

    def write_string(self, value: str, *, max_chars: int = DEFAULT_MAX_STRING_CHARS) -> None:
        """Write a UTF-8 string prefixed with its byte length."""
        raw = value.encode("utf-8")
        if len(value) > max_chars:
            raise MalformedPacket("string too long", length=len(value), max=max_chars)
        self.write_varint(len(raw))
        self._buf += raw

    def write_string_body(self, value: str, *, max_chars: int = DEFAULT_MAX_STRING_CHARS) -> None:
        """Write a UTF-8 string body with no length prefix."""
        if len(value) > max_chars:
            raise MalformedPacket("string too long", length=len(value), max=max_chars)
        self._buf += value.encode("utf-8")

    def write_raw_string(self, value: str) -> None:
        """Write a length-prefixed UTF-8 string whose prefix counts *bytes* (NBT-style)."""
        raw = value.encode("utf-8")
        self.write_u16(len(raw))
        self._buf += raw

    def write_uuid(self, value: object) -> None:
        self._buf += value.bytes  # type: ignore[attr-defined]

    def write_position(self, pos: BlockPos, *, packed_xzy: bool | None = None) -> None:
        if packed_xzy is None:
            packed_xzy = self.features.position_packed_xzy
        self.write_u64(pack_position(pos, packed_xzy=packed_xzy))

    def write_nbt(self, value: object, *, named: bool | None = None, name: str = "") -> None:
        if named is None:
            named = not self.features.network_nbt_nameless
        self._buf += write_nbt(value, named=named, name=name)

    def write_slot(self, stack: object, features: Features | None = None) -> None:
        write_slot(stack, self, features or self.features)  # type: ignore[arg-type]

    def write_bitset(self, values: tuple[int, ...] | list[int]) -> None:
        write_bitset(values, self)
