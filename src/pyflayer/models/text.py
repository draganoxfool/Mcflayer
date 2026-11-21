"""Minecraft chat components.

The wire format for 1.8.9 is a JSON chat component (for 1.20.3+ some packets use NBT, handled in
``protocol.types.nbt``). This module normalizes both a str and a JSON object into a frozen tree and
flattens it to plain text.

Examples:
    >>> comp = ChatComponent.parse({"text": "Hello ", "extra": [{"text": "world"}]})
    >>> comp.plain_text()
    'Hello world'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Self

__all__ = ["ChatComponent", "chat_component_from_json", "plain_text_from_json"]


@dataclass(frozen=True, slots=True)
class ChatComponent:
    """A parsed chat component.

    Attributes:
        text: Literal text (may be empty).
        translate: Translation key, if this is a ``translate`` component.
        with_args: Arguments for the translation key.
        extra: Child components appended after this one.
        color: Legacy color name, if present.
        bold, italic, underlined, strikethrough, obfuscated: Formatting flags.
    """

    text: str = ""
    translate: str | None = None
    with_args: tuple[ChatComponent, ...] = ()
    extra: tuple[ChatComponent, ...] = ()
    color: str | None = None
    bold: bool = False
    italic: bool = False
    underlined: bool = False
    strikethrough: bool = False
    obfuscated: bool = False

    @classmethod
    def parse(cls, raw: object) -> Self:
        """Parse a JSON string, mapping or list into a component.

        Unknown keys are ignored, so plugin output cannot make parsing fail. A ``None`` or invalid
        value becomes an empty component.
        """
        if isinstance(raw, ChatComponent):
            return raw
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith(("{", "[")):
                try:
                    return cls.parse(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
            return cls(text=raw)
        if isinstance(raw, (list, tuple)):
            children = tuple(cls.parse(item) for item in raw)
            if not children:
                return cls()
            first, *rest = children
            return cls(
                text=first.text,
                translate=first.translate,
                with_args=first.with_args,
                extra=first.extra + tuple(rest),
                color=first.color,
                bold=first.bold,
                italic=first.italic,
                underlined=first.underlined,
                strikethrough=first.strikethrough,
                obfuscated=first.obfuscated,
            )
        if not isinstance(raw, dict):
            return cls(text=str(raw))

        def flag(key: str) -> bool:
            return bool(raw.get(key, False))

        def args(key: str) -> tuple[ChatComponent, ...]:
            value = raw.get(key)
            if isinstance(value, (list, tuple)):
                return tuple(cls.parse(item) for item in value)
            return ()

        text = raw.get("text", "")
        translate = raw.get("translate")
        return cls(
            text=text if isinstance(text, str) else str(text),
            translate=translate if isinstance(translate, str) else None,
            with_args=args("with"),
            extra=args("extra"),
            color=raw.get("color") if isinstance(raw.get("color"), str) else None,
            bold=flag("bold"),
            italic=flag("italic"),
            underlined=flag("underlined"),
            strikethrough=flag("strikethrough"),
            obfuscated=flag("obfuscated"),
        )

    def plain_text(self, *, translate: dict[str, str] | None = None) -> str:
        """Flatten to text. ``translate`` optionally maps translation keys to English."""
        parts: list[str] = []
        if self.translate is not None:
            template = (translate or {}).get(self.translate, self.translate)
            try:
                parts.append(template.format(*(arg.plain_text(translate=translate) for arg in self.with_args)))
            except (IndexError, KeyError, ValueError):
                parts.append(template)
        parts.append(self.text)
        for child in self.extra:
            parts.append(child.plain_text(translate=translate))
        return "".join(parts)

    def to_json(self) -> dict[str, Any]:
        """Serialize back to a minimal JSON component dict."""
        out: dict[str, Any] = {}
        if self.text:
            out["text"] = self.text
        if self.translate is not None:
            out["translate"] = self.translate
        if self.with_args:
            out["with"] = [arg.to_json() for arg in self.with_args]
        if self.color:
            out["color"] = self.color
        for name in ("bold", "italic", "underlined", "strikethrough", "obfuscated"):
            if getattr(self, name):
                out[name] = True
        if self.extra:
            out["extra"] = [child.to_json() for child in self.extra]
        return out

    def __str__(self) -> str:
        return self.plain_text()


def chat_component_from_json(data: str | bytes) -> ChatComponent:
    """Parse a JSON chat payload, falling back to literal text on malformed input."""
    try:
        return ChatComponent.parse(json.loads(data))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ChatComponent(text=bytes(data).decode("utf-8", "replace") if isinstance(data, bytes) else data)


def plain_text_from_json(data: str | bytes) -> str:
    """Parse and flatten a JSON chat payload."""
    return chat_component_from_json(data).plain_text()
