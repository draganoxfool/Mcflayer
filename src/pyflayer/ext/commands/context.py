"""Invocation context passed to commands and checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyflayer.models.chat import ChatMessage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pyflayer.ext.commands.bot import Bot
    from pyflayer.ext.commands.core import Command
    from pyflayer.ext.commands.view import StringView

__all__ = ["Context"]


class Context:
    """State for one command invocation.

    Attributes:
        bot: The command bot that dispatched the invocation.
        message: The normalized chat message that triggered it.
        author: Sender name from the chat line, when known.
        sender_name: Stable sender identifier used for cooldown buckets and owner checks.
        invoked_with: The command name or alias that was used.
        command: The resolved command, or ``None`` while dispatching.
        args: Positional arguments after conversion.
        kwargs: Keyword arguments after conversion.
        view: The argument view positioned after the command name.
        is_whisper: True when the invocation came from a private message.
        prefix: The command prefix that matched, or ``None`` for address-only dispatch.
    """

    __slots__ = (
        "bot",
        "message",
        "author",
        "sender_name",
        "invoked_with",
        "command",
        "args",
        "kwargs",
        "view",
        "is_whisper",
        "prefix",
    )

    def __init__(
        self,
        *,
        bot: Bot,
        message: ChatMessage,
        author: str | None,
        sender_name: str,
        invoked_with: str,
        command: Command | None,
        view: StringView,
        is_whisper: bool = False,
        prefix: str | None = None,
    ) -> None:
        self.bot = bot
        self.message = message
        self.author = author
        self.sender_name = sender_name
        self.invoked_with = invoked_with
        self.command = command
        self.args: list[Any] = []
        self.kwargs: dict[str, Any] = {}
        self.view = view
        self.is_whisper = is_whisper
        self.prefix = prefix

    async def reply(self, content: str, *, whisper: bool | None = None) -> None:
        """Reply to the invoker.

        By default a whisper is answered with a whisper and public chat with public chat. Pass
        ``whisper`` to force either channel. Leading ``/`` is stripped: command output cannot
        become a server command.
        """
        content = content.lstrip("/")
        if not content:
            return
        private = self.is_whisper if whisper is None else whisper
        if private and self.author:
            await self.bot.send_command(f"msg {self.author} {content}")
            return
        await self.bot.chat(content)

    async def send(self, content: str) -> None:
        """Send a line to public chat (rate limited). Leading ``/`` is stripped."""
        content = content.lstrip("/")
        if content:
            await self.bot.chat(content)

    def __repr__(self) -> str:
        return (
            f"Context(author={self.sender_name!r}, invoked_with={self.invoked_with!r}, "
            f"is_whisper={self.is_whisper})"
        )
