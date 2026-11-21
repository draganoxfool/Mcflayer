from __future__ import annotations

import pytest

from pyflayer.bot.inventory import HOTBAR_START, Inventory, PLAYER_WINDOW, Window
from pyflayer.models.items import ItemStack


def test_player_window_defaults() -> None:
    inv = Inventory()
    assert inv.player.window_id == 0
    assert len(inv.player.items) == 45
    assert inv.held_item is None


def test_window_items_and_slots() -> None:
    inv = Inventory()
    items = [ItemStack() for _ in range(45)]
    items[0] = ItemStack(item_id=1, count=1)
    items[HOTBAR_START] = ItemStack(item_id=276, count=1)
    inv.apply_window_items(0, items)
    assert inv.player.slot(0).item_id == 1
    assert inv.held_item is not None and inv.held_item.item_id == 276
    inv.apply_set_slot(0, HOTBAR_START + 1, ItemStack(item_id=5, count=64))
    inv.set_held_slot(1)
    assert inv.held_item is not None and inv.held_item.item_id == 5
    assert inv.held_item_in(0).item_id == 276


def test_extra_windows_open_close() -> None:
    inv = Inventory()
    chest = inv.open_window(1, "Chest", 27)
    assert chest.size == 27
    assert inv.window(1) is chest
    inv.apply_set_slot(1, 3, ItemStack(item_id=4, count=1))
    assert chest.slot(3).item_id == 4
    assert inv.close_window(1) is chest
    assert inv.window(1) is None
    assert inv.close_window(0) is None


@pytest.mark.parametrize(
    ("kind", "container_slots"),
    [
        ("minecraft:chest", 27),
        ("minecraft:trapped_chest", 27),
        ("minecraft:crafting_table", 10),
        ("minecraft:furnace", 3),
        ("minecraft:dispenser", 9),
        ("minecraft:dropper", 9),
        ("minecraft:hopper", 5),
        ("minecraft:beacon", 1),
        ("minecraft:brewing_stand", 4),
        ("minecraft:enchanting_table", 2),
        ("minecraft:anvil", 3),
        ("minecraft:villager", 3),
    ],
)
def test_container_windows_keep_container_slots_before_player_copy(
    kind: str, container_slots: int
) -> None:
    """Verify container windows correctly report container_slots and accept items."""
    inv = Inventory()
    window = inv.open_window(1, kind, container_slots + 36, kind=kind)
    assert window.kind == kind
    assert window.container_slots == container_slots

    # Verify items can be set in container slots (first `container_slots` slots)
    items = [ItemStack() for _ in range(container_slots + 36)]
    items[0] = ItemStack(item_id=54, count=1)
    items[container_slots] = ItemStack(item_id=276, count=1)
    inv.apply_window_items(1, items)
    assert window.slot(0).item_id == 54
    assert window.slot(container_slots).item_id == 276
    # Verify player-inventory copy slots exist (index > container_slots)
    # Slot 35 is the last player-inventory slot; it may be empty initially
    assert window.items[container_slots + 35].count == 0


def test_clear_resets() -> None:
    inv = Inventory()
    inv.open_window(2)
    inv.set_held_slot(5)
    inv.clear()
    assert inv.window(2) is None
    assert inv.held_slot == 0
