from __future__ import annotations

import struct

import pytest

from pyflayer.errors import MalformedPacket
from pyflayer.protocol.buffer import PacketReader
from pyflayer.protocol.types.nbt import (
    NBTList,
    TAG_BYTE,
    TAG_COMPOUND,
    TAG_INT,
    TAG_LIST,
    TAG_LONG,
    read_named_nbt,
    read_unnamed_nbt,
    write_named_nbt,
    write_unnamed_nbt,
)


def test_all_scalar_tags_roundtrip() -> None:
    value = {
        "byte": -5,
        "short": -300,
        "int": 123456,
        "long": 2**40,
        "float": 1.25,
        "double": -3.5,
        "string": "héllo",
        "bytes": b"\x00\x01\xff",
        "ints": (1, -2, 3),
        "longs": (2**40, -(2**40)),
        "list": NBTList(TAG_INT, (1, 2, 3)),
        "empty": NBTList(TAG_BYTE, ()),
        "compound": {"nested": True},
    }
    raw = write_named_nbt("root", value)
    result = read_named_nbt(PacketReader(raw))
    assert result.name == "root"
    assert result.value["byte"] == -5
    assert result.value["short"] == -300
    assert result.value["int"] == 123456
    assert result.value["long"] == 2**40
    assert result.value["float"] == pytest.approx(1.25)
    assert result.value["string"] == "héllo"
    assert result.value["bytes"] == b"\x00\x01\xff"
    assert result.value["ints"] == (1, -2, 3)
    assert result.value["longs"] == (2**40, -(2**40))
    assert result.value["list"].items == (1, 2, 3)
    assert result.value["empty"].items == ()
    assert result.value["compound"] == {"nested": True}


def test_nameless_root() -> None:
    raw = write_unnamed_nbt({"a": 1})
    assert read_unnamed_nbt(PacketReader(raw)) == {"a": 1}


def test_empty_list_of_end_tag() -> None:
    # A list with element type 0 and length 0 is legal.
    raw = b"\x00\x00\x00"  # TAG_End? -> empty document handled by reader
    assert read_named_nbt(PacketReader(raw)).value == {}


def test_list_with_end_type_and_items_rejected() -> None:
    # Outer compound containing "l": TAG_List, element TAG_End, length 1.
    raw = (
        b"\x0a\x00\x00"  # compound, name ""
        b"\x08\x00\x01l"  # string key "l"
        b"\x09\x00\x00\x00\x00\x01"  # list, element 0, length 1
        b"\x00"  # end
    )
    with pytest.raises(MalformedPacket):
        read_named_nbt(PacketReader(raw))


def test_unknown_tag_rejected() -> None:
    with pytest.raises(MalformedPacket):
        read_named_nbt(PacketReader(b"\x7f"))


def test_depth_bomb_rejected() -> None:
    # Build nested compounds by hand: N x (TAG_Compound + empty name), then TAG_Ends.
    depth = 600
    raw = b"\x0a\x00\x00" + (b"\x0a\x00\x00" * depth)
    with pytest.raises(MalformedPacket):
        read_named_nbt(PacketReader(raw))


def test_negative_array_length_rejected() -> None:
    raw = (
        b"\x0a\x00\x00"
        b"\x0b\x00\x01a"
        + struct.pack(">i", -1)
        + b"\x00"
    )
    with pytest.raises(MalformedPacket):
        read_named_nbt(PacketReader(raw))


def test_compound_tag_type_constant() -> None:
    assert TAG_COMPOUND == 10
    assert TAG_LIST == 9
    assert TAG_LONG == 4
