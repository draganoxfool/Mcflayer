"""Inventory-window actions (1.8 ``window_click`` and friends).

These are the packet-level primitives. They deliberately do not guess click results: the server
answers with ``set_slot``/``window_items``, and :class:`~pyflayer.bot.inventory.Inventory` stores
that authoritative state.

The same raw-slot rules apply to every container: chest, trapped chest, crafting table, furnace,
dispenser, hopper, beacon, anvil, brewing stand, villager and horse windows. Container slots come
first, followed by the 36 player-inventory slots (27 main + 9 hotbar). Use
:attr:`Window.container_slots` to find where the player copy begins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyflayer.bot.inventory import (
    HOTBAR_SLOTS,
    HOTBAR_START,
    ClickMode,
)
from pyflayer.events.catalog import InventoryChangedEvent
from pyflayer.models.items import ItemStack

if TYPE_CHECKING:
    from pyflayer.bot.bot import Bot

__all__ = [
    "click_slot",
    "close_window",
    "drop_slot",
    "select_hotbar",
    "shift_click_slot",
]


async def select_hotbar(bot: Bot, slot: int) -> None:
    """Select hotbar slot ``0..8`` and mirror it locally."""
    slot = int(slot)
    if not 0 <= slot < HOTBAR_SLOTS:
        raise ValueError(f"hotbar slot must be 0..{HOTBAR_SLOTS - 1}, got {slot}")
    await bot._send_play("held_item_slot", {"slotId": slot})
    bot.inventory.set_held_slot(slot)
    bot.events.dispatch(InventoryChangedEvent(0, HOTBAR_START + slot, bot.inventory.held_item))


async def click_slot(
    bot: Bot,
    slot: int,
    *,
    button: int = 0,
    mode: int | ClickMode = ClickMode.LEFT,
    window_id: int = 0,
    item: ItemStack | None = None,
) -> int:
    """Send a raw ``window_click`` and return its action number."""
    window = bot.inventory.window(window_id)
    if window is None:
        raise ValueError(f"window {window_id} is not open")
    if item is None:
        item = window.slot(int(slot)) or ItemStack()
    action = bot.inventory.next_click_action()
    await bot._send_play(
        "window_click",
        {
            "windowId": int(window_id),
            "slot": int(slot),
            "mouseButton": int(button),
            "action": action,
            "mode": int(mode),
            "item": item,
        },
    )
    return action


async def shift_click_slot(bot: Bot, slot: int, *, button: int = 0, window_id: int = 0) -> int:
    """Shift-click a slot (quick-move between container and inventory)."""
    mode = ClickMode.SHIFT_LEFT if button == 0 else ClickMode.SHIFT_RIGHT
    return await click_slot(bot, slot, button=button, mode=mode, window_id=window_id)


async def drop_slot(bot: Bot, slot: int, *, all: bool = False, window_id: int = 0) -> int:
    """Drop one item or the whole stack from a slot."""
    mode = ClickMode.DROP_ALL if all else ClickMode.DROP
    return await click_slot(bot, slot, mode=mode, window_id=window_id)


async def close_window(bot: Bot, window_id: int = 0) -> None:
    """Close a window server-side and drop its local state."""
    await bot._send_play("close_window", {"windowId": int(window_id)})
    bot.inventory.close_window(window_id)
    bot.inventory.cursor = ItemStack()
