"""Normalized chat messages.

Servers and plugins format chat in many ways. :class:`ChatMessage` is the version-independent shape
the bot layer emits, with the original component retained for callers that need colours or hover
events.

Examples:
    >>> msg = ChatMessage(content="hi", sender="Steve", position="chat")
    >>> msg.is_whisper
    False
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyflayer.models.text import ChatComponent

__all__ = ["ChatMessage", "CHAT_POSITIONS"]

#: 1.8 chat packet positions.
CHAT_POSITIONS = {0: "chat", 1: "system", 2: "action_bar"}


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A chat line after parsing.

    Attributes:
        content: Plain-text message body (formatting codes preserved).
        sender: Best-effort sender name, or ``None`` for server messages.
        position: ``"chat"``, ``"system"`` or ``"action_bar"``.
        is_whisper: True when the line looks like a private message.
        component: The parsed chat component.
        raw: The original JSON mapping, for plugin-specific parsing.
    """

    content: str
    sender: str | None = None
    position: str = "chat"
    is_whisper: bool = False
    component: ChatComponent = field(default_factory=ChatComponent)
    raw: dict[str, object] = field(default_factory=dict, repr=False, compare=False)

    def __str__(self) -> str:
        return f"<{self.sender}> {self.content}" if self.sender else self.content
