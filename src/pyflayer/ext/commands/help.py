"""Help formatting.

There is no prefix to display and no paginated embed system; help is plain text that fits a chat
line. :meth:`Bot.format_help` builds the message and :class:`HelpCommand` implements a ``help``
command around it.
"""

from __future__ import annotations

from typing import Any

from pyflayer.ext.commands.core import Command, Group

__all__ = ["HelpCommand", "format_help"]


def _format_command(command: Command, *, indent: str = "") -> list[str]:
    lines = [f"{indent}{command.name}"]
    if command.aliases:
        lines[0] += f" (aliases: {', '.join(command.aliases)})"
    doc = command.short_doc
    if doc:
        lines[0] += f" - {doc}"
    if isinstance(command, Group):
        for sub in sorted(set(command.commands.values()), key=lambda item: item.name):
            lines.extend(_format_command(sub, indent=indent + "  "))
    return lines


def format_help(bot: Any, command: Command | None = None) -> str:
    """Render help for one command or for every command.

    Args:
        bot: The command bot.
        command: Optional command to describe; ``None`` lists the top-level commands.

    Returns:
        A newline-separated help string.
    """
    if command is not None:
        lines = [f"{command.qualified_name}"]
        if command.description:
            lines.append(command.description)
        return "\n".join(lines)
    lines = ["Commands:"]
    for item in sorted(set(bot.commands.values()), key=lambda item: item.name):
        if item.hidden:
            continue
        lines.extend(_format_command(item, indent="  "))
    if not lines[1:]:
        return "No commands are registered."
    return "\n".join(lines)


class HelpCommand(Command):
    """A ``help`` command backed by :func:`format_help`."""

    def __init__(self, **kwargs: Any) -> None:
        async def callback(ctx: Any, name: str | None = None) -> None:
            target = ctx.bot.get_command(name) if name else None
            await ctx.reply(format_help(ctx.bot, target))

        callback.__name__ = "help"
        super().__init__(callback, name="help", brief="Show command help", **kwargs)
