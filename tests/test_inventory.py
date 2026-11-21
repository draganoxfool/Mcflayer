from __future__ import annotations

from pyflayer.bot.inventory import HOTBAR_START, Inventory
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


def test_clear_resets() -> None:
    inv = Inventory()
    inv.open_window(2)
    inv.set_held_slot(5)
    inv.clear()
    assert inv.window(2) is None
    assert inv.held_slot == 0
