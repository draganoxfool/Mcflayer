"""Chat parsing and outbound rate limiting.

1.8 sends chat as a JSON component plus a position byte. Plugins wrap player messages in the
``chat.type.text`` translation key with the rank-formatted name as the first argument, so the
parser unwraps that key to recover a sender and body.

Outbound chat uses a token bucket (default one message per 1.1 s, burst 3) and splits anything over
the 256-character protocol limit, which avoids the most common "spam" kicks.

Examples:
    >>> parse_chat_json(
    ...     '{"translate":"chat.type.text","with":[{"text":"Steve"},{"text":"hi"}]}', 0
    ... ).sender
    'Steve'
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pyflayer._internal.clock import Clock
from pyflayer.models.chat import CHAT_POSITIONS, ChatMessage
from pyflayer.models.text import ChatComponent

__all__ = ["MAX_CHAT_CHARS", "TRANSLATIONS", "ChatQueue", "parse_chat_json"]

MAX_CHAT_CHARS = 256

#: English templates for the translation keys that appear in chat lines.
TRANSLATIONS = {
    "chat.type.text": "{0}: {1}",
    "chat.type.announcement": "[{0}] {1}",
    "chat.type.emote": "* {0} {1}",
    "chat.type.admin": "[{0}: {1}]",
    "commands.message.display.incoming": "{0} whispers to you: {1}",
    "commands.message.display.outgoing": "You whisper to {0}: {1}",
    "multiplayer.player.joined": "{0} joined the game",
    "multiplayer.player.left": "{0} left the game",
    "death.attack.generic": "{0} died",
    "chat.type.achievement": "{0} has just earned the achievement {1}",
}

_WHISPER_KEYS = frozenset(
    {"commands.message.display.incoming", "commands.message.display.outgoing"}
)
_MESSAGE_KEYS = frozenset(
    {
        "chat.type.text",
        "chat.type.emote",
        "commands.message.display.incoming",
        "commands.message.display.outgoing",
    }
)


def parse_chat_json(raw: str | bytes, position: int = 0) -> ChatMessage:
    """Parse a 1.8 chat packet payload into a :class:`ChatMessage`.

    Malformed JSON degrades to a literal-text message instead of raising, because a single broken
    plugin line should not disconnect the bot.
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    data: Any = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None
    component = ChatComponent.parse(data if data is not None else text)
    sender: str | None = None
    content = component.plain_text(translate=TRANSLATIONS)

    translate = component.translate
    if translate in _MESSAGE_KEYS and len(component.with_args) >= 2:
        sender = component.with_args[0].plain_text(translate=TRANSLATIONS).strip()
        content = component.with_args[1].plain_text(translate=TRANSLATIONS)

    return ChatMessage(
        content=content,
        sender=sender or None,
        position=CHAT_POSITIONS.get(position, "chat"),
        is_whisper=translate in _WHISPER_KEYS,
        component=component,
        raw=data if isinstance(data, dict) else {},
    )


def split_message(message: str, *, limit: int = MAX_CHAT_CHARS) -> list[str]:
    """Split a message into protocol-sized chunks without breaking UTF-8 characters."""
    if len(message) <= limit:
        return [message]
    chunks: list[str] = []
    remaining = message
    while len(remaining) > limit:
        cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class ChatQueue:
    """Outbound chat rate limiter.

    Args:
        send: Callable that actually writes one message.
        clock: Injected clock, so rate-limit tests are deterministic.
        per: Seconds between messages.
        burst: Messages allowed back-to-back before the limit applies.
    """

    __slots__ = ("_burst", "_clock", "_last_refill", "_per", "_send", "_tokens")

    def __init__(
        self,
        send: Callable[[str], Awaitable[None]],
        *,
        clock: Clock,
        per: float = 1.1,
        burst: int = 3,
    ) -> None:
        self._send = send
        self._clock = clock
        self._per = max(0.0, per)
        self._burst = max(1, burst)
        self._tokens = float(self._burst)
        self._last_refill: float | None = None

    async def send(self, message: str, *, allow_commands: bool = False) -> None:
        """Rate-limit, split and send one logical message.

        With ``allow_commands=True`` a leading ``/`` is preserved and treated as a command;
        commands are never split across packets. With the default (``False``) a leading ``/`` is
        stripped so untrusted chat cannot execute a command.
        """
        if not allow_commands:
            message = message.lstrip("/")
            if not message:
                return
        # Commands must stay in one packet; ordinary chat is split at the 256-character limit.
        chunks = [message] if message.startswith("/") else split_message(message)
        for chunk in chunks:
            await self._acquire()
            await self._send(chunk)

    async def _acquire(self) -> None:
        if self._per <= 0:
            return
        now = self._clock.monotonic()
        if self._last_refill is None:
            self._last_refill = now
        else:
            self._tokens = min(
                float(self._burst),
                self._tokens + (now - self._last_refill) / self._per,
            )
            self._last_refill = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return
        wait = (1.0 - self._tokens) * self._per
        await self._clock.sleep(wait)
        self._tokens = 0.0
        self._last_refill = self._clock.monotonic()
