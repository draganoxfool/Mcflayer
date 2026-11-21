"""Player inventory and window state (1.8 slot layout).

Window 0 is the player inventory: slot 0 is the crafting output, 1-4 the crafting grid, 5-8 armour,
9-35 the main inventory and 36-44 the hotbar. Container windows append their own slots and then a
copy of the player inventory; slot numbers sent in clicks are raw window slots, not hotbar indices.

The inventory tracks server-confirmed contents. :meth:`Bot.click_slot` sends a click and lets the
server's ``set_slot``/``window_items`` packets update this state; it does not guess the result.

Examples:
    >>> inv = Inventory()
    >>> inv.held_item is None
    True
    >>> inv.next_click_action()
    1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from pyflayer.models.items import ItemStack

__all__ = [
    "CURSOR_EVENT_SLOT",
    "CURSOR_SLOT",
    "HOTBAR_SLOTS",
    "HOTBAR_START",
    "PLAYER_WINDOW",
    "ClickMode",
    "Inventory",
    "Window",
]

PLAYER_WINDOW = 0
HOTBAR_START = 36
HOTBAR_SLOTS = 9
PLAYER_WINDOW_SIZE = 45

#: Wire slot used by ``set_slot`` for the item held by the mouse cursor.
CURSOR_SLOT = -1

#: ``InventoryChangedEvent.slot`` value used for cursor changes (the wire slot is ``-1``).
CURSOR_EVENT_SLOT = -2


class ClickMode(IntEnum):
    """1.8 ``window_click`` modes."""

    LEFT = 0
    RIGHT = 1
    SHIFT_LEFT = 2
    SHIFT_RIGHT = 3
    DROP = 4
    DROP_ALL = 5
    DRAG_LEFT = 6
    DRAG_RIGHT = 7
    DOUBLE = 8


@dataclass(slots=True)
class Window:
    """A server-side container window."""

    window_id: int
    title: str = ""
    size: int = PLAYER_WINDOW_SIZE
    items: list[ItemStack] = field(default_factory=list)
    state_id: int = 0
    kind: str = ""

    def __post_init__(self) -> None:
        if not self.items:
            self.items = [ItemStack() for _ in range(self.size)]

    @property
    def container_slots(self) -> int:
        """Slots before the player-inventory copy (chest 27, crafting table 10, furnace 3).

        Vanilla's ``open_window.slotCount`` includes the 36 player-inventory slots, so this is
        derived from the window size. Window 0 is the player inventory itself and returns 9.
        """
        return max(0, self.size - 36)

    def slot(self, index: int) -> ItemStack | None:
        """Item in a slot (``None`` when out of range or empty)."""
        if not 0 <= index < len(self.items):
            return None
        item = self.items[index]
        return None if item.empty else item

    def set_slot(self, index: int, item: ItemStack) -> None:
        """Replace one slot."""
        if 0 <= index < len(self.items):
            self.items[index] = item


class Inventory:
    """All open windows, the selected hotbar slot and the cursor stack."""

    __slots__ = ("_click_action", "cursor", "held_slot", "windows")

    def __init__(self) -> None:
        self.windows: dict[int, Window] = {PLAYER_WINDOW: Window(PLAYER_WINDOW)}
        self.held_slot = 0
        self.cursor: ItemStack = ItemStack()
        self._click_action = 0

    @property
    def player(self) -> Window:
        """The player's own window (0)."""
        return self.windows[PLAYER_WINDOW]

    def window(self, window_id: int) -> Window | None:
        """Window by id."""
        return self.windows.get(window_id)

    def next_click_action(self) -> int:
        """Return the next 1.8 window-click action number.

        Vanilla increments this for every click and wraps in the signed 16-bit range. The server
        uses it to acknowledge the click; reusing a number can make the server ignore the click.
        """
        self._click_action = (self._click_action + 1) & 0x7FFF
        if self._click_action == 0:
            self._click_action = 1
        return self._click_action

    def apply_window_items(self, window_id: int, items: list[ItemStack]) -> Window:
        """Replace a window's contents (``window_items``)."""
        window = self.windows.get(window_id)
        if window is None:
            window = Window(window_id, size=max(PLAYER_WINDOW_SIZE, len(items)))
            self.windows[window_id] = window
        window.items = list(items)
        window.size = len(items)
        return window

    def apply_set_slot(self, window_id: int, slot: int, item: ItemStack) -> Window | None:
        """Update one slot (``set_slot``), including the cursor slot ``-1``."""
        window = self.windows.get(window_id)
        if window is None:
            return None
        if slot == CURSOR_SLOT:
            self.cursor = item
            return window
        window.set_slot(slot, item)
        return window

    def set_held_slot(self, slot: int) -> None:
        """Select a hotbar slot and mirror it to the inventory window."""
        self.held_slot = max(0, min(HOTBAR_SLOTS - 1, int(slot)))

    @property
    def held_item(self) -> ItemStack | None:
        """Item in the selected hotbar slot."""
        return self.player.slot(HOTBAR_START + self.held_slot)

    def held_item_in(self, slot: int) -> ItemStack | None:
        """Item in a specific hotbar slot."""
        return self.player.slot(HOTBAR_START + max(0, min(HOTBAR_SLOTS - 1, slot)))

    def open_window(
        self,
        window_id: int,
        title: str = "",
        size: int = PLAYER_WINDOW_SIZE,
        *,
        kind: str = "",
    ) -> Window:
        """Record an opened container from ``open_window`` (size is the total slot count)."""
        window = Window(window_id, title=title, size=size, kind=kind)
        self.windows[window_id] = window
        return window

    def close_window(self, window_id: int) -> Window | None:
        """Drop a closed container (the player window is kept)."""
        if window_id == PLAYER_WINDOW:
            return None
        return self.windows.pop(window_id, None)

    def clear(self) -> None:
        """Reset to an empty player inventory."""
        self.windows = {PLAYER_WINDOW: Window(PLAYER_WINDOW)}
        self.held_slot = 0
        self.cursor = ItemStack()
        self._click_action = 0

    def __repr__(self) -> str:
        return f"Inventory(windows={len(self.windows)}, held_slot={self.held_slot})"
