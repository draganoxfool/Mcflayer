"""Bot composition root (M2: protocol + events; world/physics arrive later)."""

from __future__ import annotations

from pyflayer.bot.bot import Bot, BotState, PlayerInfo
from pyflayer.bot.chat import ChatQueue, parse_chat_json, split_message

__all__ = [
    "Bot",
    "BotState",
    "ChatQueue",
    "PlayerInfo",
    "parse_chat_json",
    "split_message",
]
