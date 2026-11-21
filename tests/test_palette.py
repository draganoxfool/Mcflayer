from __future__ import annotations

import numpy as np
import pytest

from pyflayer.errors import OutOfWorldBounds
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.varint import encode_varint
from pyflayer.world.palette import ContainerKind, PalettedContainer


def test_single_container_is_zero_storage() -> None:
    box = PalettedContainer.single(0)
    assert box.kind is ContainerKind.SINGLE
    assert box.get(1234) == 0
    assert box.to_array().tolist() == [0] * 4096


def test_single_with_set_upgrades_to_indirect_and_is_cow() -> None:
    box = PalettedContainer.single(0)
    changed = box.with_set(5, 16)
    assert changed.kind is ContainerKind.INDIRECT
    assert changed.get(5) == 16
    assert changed.get(0) == 0
    assert box.get(5) == 0  # original untouched
    assert not changed.indices.flags.writeable


def test_indirect_grows_palette_and_bits() -> None:
    box = PalettedContainer.single(0)
    for index, value in enumerate(range(16, 40)):
        box = box.with_set(index, value)
    assert box.get(0) == 16
    assert box.get(23) == 39
    assert box.bits_per_entry >= 5
    assert box.with_set(0, 16) is box  # no-op returns the same object


def test_direct_container_with_set() -> None:
    values = np.arange(4096, dtype=np.uint16)
    box = PalettedContainer.direct(values)
    assert box.get(100) == 100
    changed = box.with_set(100, 7)
    assert changed.get(100) == 7
    assert box.get(100) == 100
    assert changed.kind is ContainerKind.DIRECT


def test_index_bounds() -> None:
    box = PalettedContainer.single(0)
    with pytest.raises(OutOfWorldBounds):
        box.get(4096)
    with pytest.raises(OutOfWorldBounds):
        box.with_set(-1, 1)


def _container_bytes(bits: int, palette: list[int], values: list[int], *, spanning: bool = False) -> bytes:
    count = len(values)
    if spanning:
        total_bits = count * bits
        packed = 0
        for index, value in enumerate(values):
            packed |= value << (index * bits)
        long_count = (total_bits + 63) // 64
        data = packed.to_bytes(long_count * 8, "little")
        # The wire stores longs big-endian; convert each long individually.
        longs = [int.from_bytes(data[i * 8 : i * 8 + 8], "little") for i in range(long_count)]
        raw = b"".join(value.to_bytes(8, "big") for value in longs)
    else:
        per_long = 64 // bits
        longs = []
        for start in range(0, count, per_long):
            packed = 0
            for offset, value in enumerate(values[start : start + per_long]):
                packed |= value << (offset * bits)
            longs.append(packed)
        raw = b"".join(value.to_bytes(8, "big") for value in longs)
    writer = PacketWriter()
    writer.write_u8(bits)
    writer.write_varint(len(palette))
    for value in palette:
        writer.write_varint(value)
    writer.write_varint(len(longs))
    writer.write_bytes(raw)
    return writer.to_bytes()


def test_decode_non_spanning() -> None:
    values = [(index * 3) % 8 for index in range(4096)]
    raw = _container_bytes(4, list(range(8)), values)
    box = PalettedContainer.decode(PacketReader(raw), size=4096)
    assert box.kind is ContainerKind.INDIRECT
    assert [box.get(index) for index in (0, 1, 15, 16, 17, 4095)] == [
        values[0], values[1], values[15], values[16], values[17], values[4095]
    ]


def test_decode_spanning_layout() -> None:
    values = [(index * 5) % 6 for index in range(64)]
    raw = _container_bytes(3, list(range(6)), values, spanning=True)
    box = PalettedContainer.decode(PacketReader(raw), size=64, min_bits=1, spanning=True)
    assert [box.get(index) for index in range(64)] == values


def test_decode_direct_without_palette() -> None:
    writer = PacketWriter()
    writer.write_u8(4)
    writer.write_varint(0)
    writer.write_varint(1)
    writer.write_bytes((0).to_bytes(8, "big"))
    box = PalettedContainer.decode(PacketReader(writer.to_bytes()), size=4096)
    assert box.kind is ContainerKind.DIRECT
    assert box.get(0) == 0
    assert box.get(4095) == 0


def test_decode_single() -> None:
    writer = PacketWriter()
    writer.write_u8(0)
    writer.write_varint(42)
    box = PalettedContainer.decode(PacketReader(writer.to_bytes()), size=64)
    assert box.kind is ContainerKind.SINGLE
    assert box.get(0) == 42
    assert box.get(63) == 42


def test_decode_rejects_negative_palette() -> None:
    from pyflayer.errors import MalformedPacket

    raw = bytes((4,)) + encode_varint(-1)
    with pytest.raises(MalformedPacket):
        PalettedContainer.decode(PacketReader(raw))
