"""Slot (item stack) wire codec.

Version differences are expressed through :class:`Features`:

* 1.8-1.12: ``i16 item_id`` (``-1`` = empty), ``i8 count``, ``i16 damage``, named NBT.
* 1.13-1.20.4: ``VarInt item_id`` (``0`` = empty), ``i8 count``, NBT (nameless from 1.20.2).
* 1.20.5+: structured item components are not implemented in M1; decoding raises
  :class:`~pyflayer.errors.UnsupportedType` with a pointer to the ``protocol/native`` extension point.
"""

from __future__ import annotations

from pyflayer.data.features import Features
from pyflayer.errors import UnsupportedType
from pyflayer.models.items import ItemStack
from pyflayer.protocol.types.nbt import read_nbt, write_nbt

__all__ = ["read_slot", "write_slot"]

#: Marker for the 1.20.5+ component extension point (implemented in a later milestone).
COMPONENTS_EXTENSION_POINT = "protocol/native/slot_components"


def read_slot(reader: object, features: Features) -> ItemStack:
    """Decode one slot from ``reader``."""
    if features.item_components:
        raise UnsupportedType(
            "structured item components require a native codec",
            type_name="slot",
            extension_point=COMPONENTS_EXTENSION_POINT,
        )
    if features.slot_item_id_varint:
        item_id = reader.read_varint()  # type: ignore[attr-defined]
        if item_id == 0:
            return ItemStack()
        count = reader.read_i8()  # type: ignore[attr-defined]
        nbt = read_nbt(reader, named=not features.network_nbt_nameless)  # type: ignore[arg-type]
        value = nbt.value if hasattr(nbt, "value") else nbt
        return ItemStack(item_id=item_id, count=count, nbt=value)  # type: ignore[arg-type]
    item_id = reader.read_i16()  # type: ignore[attr-defined]
    if item_id == -1:
        return ItemStack()
    count = reader.read_i8()  # type: ignore[attr-defined]
    damage = reader.read_i16()  # type: ignore[attr-defined]
    nbt = read_nbt(reader, named=not features.network_nbt_nameless)  # type: ignore[arg-type]
    value = nbt.value if hasattr(nbt, "value") else nbt
    return ItemStack(item_id=item_id, count=count, damage=damage, nbt=value)  # type: ignore[arg-type]


def write_slot(stack: ItemStack, writer: object, features: Features) -> None:
    """Encode one slot to ``writer``."""
    if features.item_components:
        raise UnsupportedType(
            "structured item components require a native codec",
            type_name="slot",
            extension_point=COMPONENTS_EXTENSION_POINT,
        )
    if features.slot_item_id_varint:
        if stack.empty:
            writer.write_varint(0)  # type: ignore[attr-defined]
            return
        writer.write_varint(stack.item_id)  # type: ignore[attr-defined]
        writer.write_i8(stack.count)  # type: ignore[attr-defined]
    else:
        if stack.empty:
            writer.write_i16(-1)  # type: ignore[attr-defined]
            return
        writer.write_i16(stack.item_id)  # type: ignore[attr-defined]
        writer.write_i8(stack.count)  # type: ignore[attr-defined]
        writer.write_i16(stack.damage)  # type: ignore[attr-defined]
    writer.write_bytes(  # type: ignore[attr-defined]
        write_nbt(stack.nbt or {}, named=not features.network_nbt_nameless)
    )
