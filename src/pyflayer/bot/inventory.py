"""Player inventory and window state (1.8 slot layout).

Window 0 is the player inventory: slot 0 is the crafting output, 1–4 the crafting grid, 5–8 armour,
9–35 the main inventory and 36–44 the hotbar. Only state is tracked in M3; clicking is M6.

Examples:
    >>> inv = Inventory()
    >>> inv.held_item is None
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyflayer.models.items import ItemStack

__all__ = ["Inventory", "Window", "PLAYER_WINDOW", "HOTBAR_START", "HOTBAR_SLOTS"]

PLAYER_WINDOW = 0
HOTBAR_START = 36
HOTBAR_SLOTS = 9
PLAYER_WINDOW_SIZE = 45


@dataclass(slots=True)
class Window:
    """A server-side container window."""

    window_id: int
    title: str = ""
    size: int = PLAYER_WINDOW_SIZE
    items: list[ItemStack] = field(default_factory=list)
    state_id: int = 0

    def __post_init__(self) -> None:
        if not self.items:
            self.items = [ItemStack() for _ in range(self.size)]

    def slot(self, index: int) -> ItemStack | None:
        """Item in a slot (``None`` when out of range)."""
        if not 0 <= index < len(self.items):
            return None
        item = self.items[index]
        return None if item.empty else item

    def set_slot(self, index: int, item: ItemStack) -> None:
        """Replace one slot."""
        if 0 <= index < len(self.items):
            self.items[index] = item


class Inventory:
    """All open windows, plus the selected hotbar slot."""

    __slots__ = ("windows", "held_slot")

    def __init__(self) -> None:
        self.windows: dict[int, Window] = {PLAYER_WINDOW: Window(PLAYER_WINDOW)}
        self.held_slot = 0

    @property
    def player(self) -> Window:
        """The player's own window (0)."""
        return self.windows[PLAYER_WINDOW]

    def window(self, window_id: int) -> Window | None:
        """Window by id."""
        return self.windows.get(window_id)

    def apply_window_items(self, window_id: int, items: list[ItemStack]) -> Window:
        """Replace a window's contents (``window_items``)."""
        window = self.windows.get(window_id)
        if window is None:
            window = Window(window_id, size=max(PLAYER_WINDOW_SIZE, len(items)))
            self.windows[window_id] = window
        window.items = list(items)
        return window

    def apply_set_slot(self, window_id: int, slot: int, item: ItemStack) -> Window | None:
        """Update one slot (``set_slot``)."""
        window = self.windows.get(window_id)
        if window is None:
            return None
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

    def open_window(self, window_id: int, title: str = "", size: int = PLAYER_WINDOW_SIZE) -> Window:
        """Record an opened container."""
        window = Window(window_id, title=title, size=size)
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

    def __repr__(self) -> str:
        return f"Inventory(windows={len(self.windows)}, held_slot={self.held_slot})"
