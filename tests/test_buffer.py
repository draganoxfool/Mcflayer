from __future__ import annotations

import uuid

import pytest

from pyflayer.data.features import Features
from pyflayer.errors import MalformedPacket
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import BlockPos
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.types.nbt import read_named_nbt, write_named_nbt
from pyflayer.protocol.types.position import pack_position, unpack_position
from pyflayer.protocol.types.slot import read_slot, write_slot

LEGACY = Features.for_version("1.8.9")
MODERN = Features.for_version("1.20.4")


def test_integer_and_float_primitives() -> None:
    writer = PacketWriter()
    writer.write_u8(255)
    writer.write_i8(-128)
    writer.write_u16(65535)
    writer.write_i16(-32768)
    writer.write_u32(2**32 - 1)
    writer.write_i32(-(2**31))
    writer.write_u64(2**64 - 1)
    writer.write_i64(-(2**63))
    writer.write_f32(1.5)
    writer.write_f64(-2.25)
    writer.write_bool(True)
    reader = PacketReader(writer.to_bytes())
    assert reader.read_u8() == 255
    assert reader.read_i8() == -128
    assert reader.read_u16() == 65535
    assert reader.read_i16() == -32768
    assert reader.read_u32() == 2**32 - 1
    assert reader.read_i32() == -(2**31)
    assert reader.read_u64() == 2**64 - 1
    assert reader.read_i64() == -(2**63)
    assert reader.read_f32() == 1.5
    assert reader.read_f64() == -2.25
    assert reader.read_bool() is True
    reader.ensure_finished()


def test_read_past_end() -> None:
    with pytest.raises(MalformedPacket):
        PacketReader(b"\x01").read_i32()


def test_strings_and_utf16_lengths() -> None:
    writer = PacketWriter()
    writer.write_string("hello")
    writer.write_string("héllo")  # 3-byte UTF-8 BMP
    writer.write_string("𝄞")  # 4-byte UTF-8, two UTF-16 code units
    writer.write_string("")
    reader = PacketReader(writer.to_bytes())
    assert reader.read_string() == "hello"
    assert reader.read_string() == "héllo"
    assert reader.read_string() == "𝄞"
    assert reader.read_string() == ""
    reader.ensure_finished()


def test_string_prefix_is_utf8_byte_length() -> None:
    writer = PacketWriter()
    writer.write_string("héllo")
    # 5 characters, 6 UTF-8 bytes: the prefix must be 6, not the character count.
    assert writer.to_bytes() == b"\x06h\xc3\xa9llo"
    # MOTD-style colour codes are 2-byte UTF-8 but one character.
    writer = PacketWriter()
    writer.write_string("§c§lHi")
    raw = writer.to_bytes()
    assert raw[0] == 8  # 2 * 2 bytes for the section signs + 4 ASCII
    assert PacketReader(raw).read_string() == "§c§lHi"


def test_string_max_length() -> None:
    writer = PacketWriter()
    writer.write_string("x" * 10)
    reader = PacketReader(writer.to_bytes())
    with pytest.raises(MalformedPacket):
        reader.read_string(max_chars=5)


def test_string_overlong_utf8_rejected() -> None:
    # Length=1 unit, then the overlong encoding of "A".
    data = b"\x01\xc1\x81"
    with pytest.raises(MalformedPacket):
        PacketReader(data).read_string()


def test_string_invalid_continuation() -> None:
    data = b"\x01\xc3\x28"
    with pytest.raises(MalformedPacket):
        PacketReader(data).read_string()


def test_trailing_bytes_strict_and_lenient() -> None:
    reader = PacketReader(b"\x01\x02")
    reader.read_u8()
    with pytest.raises(MalformedPacket):
        reader.ensure_finished()
    reader.ensure_finished(strict=False)


def test_bool_accepts_non_canonical() -> None:
    """Notchian-compatible: any non-zero byte is treated as True, not an error."""
    assert PacketReader(b"\x02").read_bool() is True


def test_uuid_roundtrip() -> None:
    value = uuid.uuid4()
    writer = PacketWriter()
    writer.write_uuid(value)
    assert PacketReader(writer.to_bytes()).read_uuid() == value


@pytest.mark.parametrize("packed_xzy", [False, True])
def test_position_roundtrip(packed_xzy: bool) -> None:
    for pos in (
        BlockPos(0, 0, 0),
        BlockPos(-1, 64, 1),
        BlockPos(2**25 - 1, 2047, -(2**25)),
        BlockPos(-(2**25), -2048, 2**25 - 1),
    ):
        packed = pack_position(pos, packed_xzy=packed_xzy)
        assert unpack_position(packed, packed_xzy=packed_xzy) == pos


def test_position_out_of_range() -> None:
    with pytest.raises(MalformedPacket):
        pack_position(BlockPos(2**25, 0, 0))
    with pytest.raises(MalformedPacket):
        pack_position(BlockPos(0, 2048, 0))


async def test_bitset_roundtrip() -> None:
    writer = PacketWriter()
    writer.write_bitset([1, -1, 0])
    reader = PacketReader(writer.to_bytes())
    assert reader.read_bitset() == (1, -1, 0)
    reader.ensure_finished()


def test_slot_legacy_roundtrip() -> None:
    stack = ItemStack(item_id=1, count=3, damage=2, nbt={"display": {"Name": "x"}})
    writer = PacketWriter(features=LEGACY)
    write_slot(stack, writer, LEGACY)
    decoded = read_slot(PacketReader(writer.to_bytes(), features=LEGACY), LEGACY)
    assert decoded.item_id == 1
    assert decoded.count == 3
    assert decoded.damage == 2
    assert decoded.nbt == {"display": {"Name": "x"}}


def test_slot_empty_legacy() -> None:
    writer = PacketWriter(features=LEGACY)
    write_slot(ItemStack(), writer, LEGACY)
    assert writer.to_bytes() == b"\xff\xff"
    assert read_slot(PacketReader(b"\xff\xff", features=LEGACY), LEGACY).empty


def test_nbt_named_roundtrip_through_reader() -> None:
    raw = write_named_nbt("", {"a": 1, "b": ["x", "y"]})
    result = read_named_nbt(PacketReader(raw))
    assert result.name == ""
    assert result.value["a"] == 1
    assert result.value["b"].tag_type == 8
    assert result.value["b"].items == ("x", "y")
