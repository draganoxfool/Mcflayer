"""Block and held-item actions (1.8 ``block_dig``/``block_place``).

Breaking and placing are packet-level helpers. They do not run the action scheduler, check reach,
or calculate survival break time; those belong to the M6 action layer. ``break_block(delay=...)``
exists so callers can honour the vanilla delay without pretending to know tool speed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyflayer.models.enums import Face
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import BlockPos

if TYPE_CHECKING:
    from pyflayer.bot.bot import Bot

__all__ = [
    "break_block",
    "cancel_digging",
    "finish_digging",
    "place_block",
    "start_digging",
    "swing_arm",
    "use_item",
]


async def swing_arm(bot: Bot) -> None:
    """Play the main-hand swing animation."""
    await bot._send_play("arm_animation", {})


async def use_item(bot: Bot) -> None:
    """Use the held item without targeting a block."""
    await bot._send_play(
        "block_place",
        {
            "location": {"x": -1, "y": -1, "z": -1},
            "direction": -1,
            "heldItem": bot.inventory.held_item or ItemStack(),
            "cursorX": 0,
            "cursorY": 0,
            "cursorZ": 0,
        },
    )


async def place_block(
    bot: Bot,
    pos: BlockPos,
    *,
    face: Face | int = Face.UP,
    cursor: tuple[int, int, int] = (8, 8, 8),
) -> None:
    """Right-click a block position with the held item."""
    if len(cursor) != 3:
        raise ValueError("cursor must contain three 0..15 coordinates")
    cx, cy, cz = (max(0, min(15, int(value))) for value in cursor)
    await bot._send_play(
        "block_place",
        {
            "location": {"x": pos.x, "y": pos.y, "z": pos.z},
            "direction": int(face),
            "heldItem": bot.inventory.held_item or ItemStack(),
            "cursorX": cx,
            "cursorY": cy,
            "cursorZ": cz,
        },
    )


async def _send_dig(bot: Bot, pos: BlockPos, face: Face | int, status: int) -> None:
    await bot._send_play(
        "block_dig",
        {
            "status": int(status),
            "location": {"x": pos.x, "y": pos.y, "z": pos.z},
            "face": int(face),
        },
    )


async def start_digging(bot: Bot, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
    """Start breaking a block (``block_dig`` status 0)."""
    await _send_dig(bot, pos, face, 0)


async def finish_digging(bot: Bot, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
    """Finish breaking a block (``block_dig`` status 2)."""
    await _send_dig(bot, pos, face, 2)


async def cancel_digging(bot: Bot, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
    """Abort a break in progress (``block_dig`` status 1)."""
    await _send_dig(bot, pos, face, 1)


async def break_block(
    bot: Bot,
    pos: BlockPos,
    *,
    face: Face | int = Face.UP,
    delay: float = 0.0,
) -> None:
    """Send start and finish digging, optionally waiting ``delay`` seconds.

    Survival servers enforce the vanilla break time. This helper does not calculate tool speed,
    effects or block hardness; pass a suitable ``delay`` or drive
    :func:`start_digging`/:func:`finish_digging` yourself. Creative mode accepts an immediate
    finish.
    """
    if delay < 0:
        raise ValueError("delay must be non-negative")
    await start_digging(bot, pos, face=face)
    if delay:
        await bot.clock.sleep(delay)
    await finish_digging(bot, pos, face=face)
