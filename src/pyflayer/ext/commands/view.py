"""A small tokenizer for command arguments.

``StringView`` is modelled on discord.py's view: it tracks a cursor over the raw message and
supports quoted words, backslash escapes and reading the remainder. Command parsing consumes tokens
from it, so quoted arguments such as ``say "hello world"`` arrive as a single value.
"""

from __future__ import annotations

__all__ = ["StringView", "tokenize"]


class StringView:
    """Cursor over a command argument string.

    Examples:
        >>> view = StringView('say "hello world"')
        >>> view.read()
        'say'
        >>> view.skip_whitespace()
        >>> view.get_quoted_word()
        'hello world'
    """

    __slots__ = ("buffer", "index")

    def __init__(self, buffer: str) -> None:
        self.buffer = buffer
        self.index = 0

    def __len__(self) -> int:
        return len(self.buffer)

    def __repr__(self) -> str:
        return f"<StringView index={self.index} buffer={self.buffer!r}>"

    @property
    def eof(self) -> bool:
        """True when the cursor has reached the end of the buffer."""
        return self.index >= len(self.buffer)

    @property
    def previous(self) -> str:
        """The character before the cursor, or an empty string at the start."""
        return self.buffer[self.index - 1] if self.index else ""

    def skip_whitespace(self) -> int:
        """Advance over spaces and return how many were skipped."""
        start = self.index
        while self.index < len(self.buffer) and self.buffer[self.index].isspace():
            self.index += 1
        return self.index - start

    def read(self) -> str:
        """Read one whitespace-delimited token (quotes handled by :meth:`get_quoted_word`)."""
        self.skip_whitespace()
        start = self.index
        while self.index < len(self.buffer) and not self.buffer[self.index].isspace():
            self.index += 1
        return self.buffer[start : self.index]

    def read_rest(self) -> str:
        """Return the remainder of the buffer, consuming it."""
        rest = self.buffer[self.index :]
        self.index = len(self.buffer)
        return rest

    def consume(self, length: int) -> None:
        """Advance the cursor by ``length`` characters."""
        self.index = min(len(self.buffer), self.index + length)

    def get_quoted_word(self) -> str | None:
        """Read a word, honouring ``"`` quoting and ``\\`` escapes.

        Returns ``None`` at end of input.
        """
        self.skip_whitespace()
        if self.eof:
            return None
        current = self.index
        result: list[str] = []
        quoted = False
        while current < len(self.buffer):
            char = self.buffer[current]
            if char == "\\" and current + 1 < len(self.buffer):
                current += 1
                result.append(self.buffer[current])
                current += 1
                continue
            if char == '"':
                quoted = not quoted
                current += 1
                continue
            if char.isspace() and not quoted:
                break
            result.append(char)
            current += 1
        self.index = current
        return "".join(result)


def tokenize(text: str) -> list[str]:
    """Split ``text`` into tokens, honouring double quotes and backslash escapes."""
    view = StringView(text)
    tokens: list[str] = []
    while True:
        token = view.get_quoted_word()
        if token is None:
            break
        tokens.append(token)
    return tokens
