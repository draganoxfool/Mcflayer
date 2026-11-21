"""Item stacks.

1.8.9 uses a 16-bit numeric item id and damage value. 1.13+ uses a namespaced item name and, from
1.20.5, structured components. M1 models the common shape and keeps a clearly-marked extension point
for structured components. The slot wire codec lives in :mod:`pyflayer.protocol.types.slot`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ItemStack", "EMPTY_ITEM"]


@dataclass(frozen=True, slots=True)
class ItemStack:
    """An immutable item stack.

    Attributes:
        item_id: Numeric id (pre-1.13) or registry id when using numeric data.
        name: Namespaced item name (``minecraft:stone``), when known.
        count: Stack size; 0 means empty.
        damage: Legacy damage/metadata value.
        nbt: Immutable-ish NBT payload (a mapping) or ``None``. Treat as read-only.
    """

    item_id: int = 0
    name: str | None = None
    count: int = 0
    damage: int = 0
    nbt: dict[str, Any] | None = field(default=None, compare=False, hash=False)

    @property
    def empty(self) -> bool:
        """True when the stack holds nothing."""
        return self.count <= 0 or self.item_id <= 0

    def with_count(self, count: int) -> ItemStack:
        """Return a copy with a new count."""
        return ItemStack(self.item_id, self.name, count, self.damage, self.nbt)


EMPTY_ITEM = ItemStack()
