"""The command bot: address-based dispatch, cogs and atomic extensions.

There is no command prefix (ADR-11). A chat line becomes a command only when it is addressed to the
bot — a whisper, or a public line that mentions the bot's name — or when code calls
:meth:`dispatch_command`. Passing ``command_prefix=`` raises :class:`CommandPrefixError`.
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from collections.abc import Callable, Collection
from typing import Any

from pyflayer.bot import Bot as _BaseBot
from pyflayer.events.catalog import ChatEvent, event_for_name
from pyflayer.ext.commands.cog import Cog
from pyflayer.ext.commands.context import Context
from pyflayer.ext.commands.core import Command, Group, command as _command, group as _group
from pyflayer.ext.commands.errors import (
    CommandError,
    CommandInvokeError,
    CommandNotFound,
    CommandPrefixError,
    ExtensionAlreadyLoaded,
    ExtensionFailed,
    ExtensionNotLoaded,
)
from pyflayer.ext.commands.help import HelpCommand
from pyflayer.ext.commands.view import StringView
from pyflayer.models.chat import ChatMessage

__all__ = ["Bot"]

_MISSING = object()


class Bot(_BaseBot):
    """A :class:`pyflayer.Bot` with commands, cogs and extensions.

    Args:
        username: Offline username.
        command_prefix: Not supported. Passing it raises :class:`CommandPrefixError`.
        trigger: Optional regex a public message may start with instead of a name mention.
        case_insensitive: Lower-case command names and aliases when resolving.
        owner_ids: Sender names considered owners by :func:`~checks.is_owner`.
        help_command: Add a built-in ``help`` command (default ``True``).
    """

    def __init__(
        self,
        username: str | None = None,
        *,
        command_prefix: object = _MISSING,
        trigger: str | re.Pattern[str] | None = None,
        case_insensitive: bool = True,
        owner_ids: Collection[str] = (),
        help_command: bool = True,
        **kwargs: Any,
    ) -> None:
        if command_prefix is not _MISSING:
            raise CommandPrefixError()
        super().__init__(username, **kwargs)
        self.trigger = re.compile(trigger) if isinstance(trigger, str) else trigger
        self.case_insensitive = case_insensitive
        self.owner_ids = frozenset(owner_ids)
        self.commands: dict[str, Command] = {}
        self.cogs: dict[str, Cog] = {}
        self._extensions: dict[str, dict[str, Any]] = {}
        self._loading_extension: str | None = None
        self._cog_subs: dict[Cog, list[Any]] = {}
        self._on_command_error: Callable[..., Any] | None = None
        self.events.subscribe(ChatEvent, self._on_chat_event)
        if help_command:
            self.add_command(HelpCommand())

    # ------------------------------------------------------------------ dispatch
    async def _on_chat_event(self, event: ChatEvent) -> None:
        await self.process_message(event.message)

    async def process_message(self, message: ChatMessage) -> None:
        """Feed one normalized chat line through the address rules."""
        if message.sender is None or message.sender == self.username:
            return
        addressed = self._addressed(message)
        if addressed is None:
            return
        text, is_whisper = addressed
        await self.dispatch_command(
            text, author=message.sender, is_whisper=is_whisper, message=message
        )

    def _addressed(self, message: ChatMessage) -> tuple[str, bool] | None:
        content = message.content
        if message.is_whisper:
            return content.strip(), True
        if not self.username:
            return None
        if self.trigger is not None:
            match = self.trigger.match(content)
            if match:
                return content[match.end():].strip(), False
        # A public line is addressed when the bot's name appears as a token. Check the
        # decorated forms first so ``@Steve help`` does not lose its ``@`` as command text.
        name = self.username
        lowered = content.lower()
        for token in (f"<{name.lower()}>", f"@{name.lower()}", name.lower()):
            index = lowered.find(token)
            while index != -1:
                before = content[index - 1] if index else " "
                after_index = index + len(token)
                after = content[after_index] if after_index < len(content) else " "
                if not before.isalnum() and not after.isalnum():
                    rest = (content[:index] + content[after_index:]).strip()
                    rest = rest.lstrip(":,").strip()
                    return rest, False
                index = lowered.find(token, index + 1)
        return None

    async def dispatch_command(
        self,
        text: str,
        *,
        author: str | None = None,
        is_whisper: bool = False,
        message: ChatMessage | None = None,
    ) -> None:
        """Dispatch ``text`` as a command, bypassing address rules.

        Raises:
            CommandNotFound: When no command matches the first token.
        """
        view = StringView(text)
        name = view.read()
        if not name:
            return
        command = self.get_command(name)
        if command is None:
            raise CommandNotFound(name)
        while isinstance(command, Group):
            saved = view.index
            token = view.get_quoted_word()
            if token is None:
                view.index = saved
                break
            sub = command.get_command(token)
            if sub is None and self.case_insensitive:
                lowered = token.lower()
                sub = next(
                    (
                        candidate
                        for key, candidate in command.commands.items()
                        if key.lower() == lowered
                    ),
                    None,
                )
            if sub is None:
                view.index = saved
                break
            command = sub
        if isinstance(command, Group) and not command.invoke_without_command:
            raise CommandNotFound(command.qualified_name)
        ctx = Context(
            bot=self,
            message=message or ChatMessage(content=text, sender=author),
            author=author,
            sender_name=author or "console",
            invoked_with=name,
            command=command,
            view=view,
            is_whisper=is_whisper,
        )
        try:
            await command.prepare(ctx)
            cog = command.cog
            if isinstance(cog, Cog):
                await cog.cog_before_invoke(ctx)
            await command.invoke(ctx)
            if isinstance(cog, Cog):
                await cog.cog_after_invoke(ctx)
        except Exception as exc:  # noqa: BLE001 - routed to the error chain
            await self._handle_error(ctx, command, exc)

    async def _handle_error(self, ctx: Context, command: Command, error: BaseException) -> None:
        if self._on_command_error is not None:
            try:
                result = self._on_command_error(ctx, error)
                if inspect.isawaitable(result):
                    await result
                return
            except Exception:  # noqa: BLE001 - fall through to the next handler
                pass
        cog = command.cog
        if isinstance(cog, Cog):
            try:
                await cog.cog_command_error(ctx, error)
                return
            except Exception:  # noqa: BLE001
                pass
        if command._error is not None:
            result = command._error(ctx, error)
            if inspect.isawaitable(result):
                await result
            return
        if isinstance(error, (CommandError,)) or isinstance(error, CommandInvokeError):
            import logging

            logging.getLogger("pyflayer.ext.commands").warning(
                "command %s failed: %s", command.qualified_name, error
            )

    # ------------------------------------------------------------------ registration
    def add_command(self, command_obj: Command) -> None:
        """Register a top-level command."""
        self.commands[command_obj.name] = command_obj
        for alias in command_obj.aliases:
            self.commands.setdefault(alias, command_obj)
        if self._loading_extension is not None:
            self._extensions[self._loading_extension]["ledger"]["commands"].append(command_obj)

    def remove_command(self, name: str) -> Command | None:
        """Remove a top-level command and its aliases."""
        command_obj = self.commands.pop(name, None)
        if command_obj is None:
            return None
        for alias, candidate in list(self.commands.items()):
            if candidate is command_obj:
                self.commands.pop(alias, None)
        return command_obj

    def get_command(self, name: str | None) -> Command | None:
        """Look up a top-level command by name or alias."""
        if name is None:
            return None
        if self.case_insensitive:
            name = name.lower()
            for key, candidate in self.commands.items():
                if key.lower() == name:
                    return candidate
            return None
        return self.commands.get(name)

    def walk_commands(self) -> list[Command]:
        """Every command, including group subcommands."""
        result: list[Command] = []
        for command_obj in set(self.commands.values()):
            result.append(command_obj)
            if isinstance(command_obj, Group):
                result.extend(command_obj.walk_commands())
        return result

    def command(self, **attrs: Any) -> Callable[..., Command]:
        """Decorator that registers a command on this bot."""

        def decorator(func: Callable[..., Any]) -> Command:
            created = _command(**attrs)(func)
            self.add_command(created)
            return created

        return decorator

    def group(self, **attrs: Any) -> Callable[..., Group]:
        """Decorator that registers a group on this bot."""

        def decorator(func: Callable[..., Any]) -> Group:
            created = _group(**attrs)(func)
            self.add_command(created)
            return created

        return decorator

    def on_command_error(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register the bot-wide command error handler."""
        self._on_command_error = coro
        return coro

    # ------------------------------------------------------------------ cogs
    async def add_cog(self, cog: Cog, *, override: bool = False) -> None:
        """Register a cog's commands, listeners and loops.

        Raises:
            CommandError: When a cog with the same name exists and ``override`` is false.
        """
        name = cog.qualified_name
        if name in self.cogs and not override:
            raise CommandError(f"cog {name!r} is already loaded")
        if name in self.cogs:
            await self.remove_cog(name)
        self.cogs[name] = cog
        for command_obj in cog.get_commands():
            self.add_command(command_obj)
        subs = []
        for event_name, callback in cog.get_listeners():
            event_type = event_for_name(event_name)
            subs.append(self.events.subscribe(event_type, callback, owner=cog))
        self._cog_subs[cog] = subs
        await cog.cog_load()
        for loop in cog.get_loops():
            loop._resume()
        if self._loading_extension is not None:
            self._extensions[self._loading_extension]["ledger"]["cogs"].append(cog)

    async def remove_cog(self, name: str) -> Cog | None:
        """Unload a cog, cancelling its loops and removing its commands."""
        cog = self.cogs.pop(name, None)
        if cog is None:
            return None
        for loop in cog.get_loops():
            loop.cancel()
        self.events.unsubscribe_owner(cog)
        self._cog_subs.pop(cog, None)
        for command_obj in cog.get_commands():
            if self.commands.get(command_obj.name) is command_obj:
                self.remove_command(command_obj.name)
        await cog.cog_unload()
        return cog

    # ------------------------------------------------------------------ extensions
    async def load_extension(self, name: str, *, package: str | None = None) -> None:
        """Import ``name`` and call its ``setup(bot)``.

        Any partial registration is rolled back when setup raises.
        """
        if name in self._extensions:
            raise ExtensionAlreadyLoaded(f"extension {name!r} is already loaded")
        module_name = name if package is None else f"{package}.{name}"
        self._extensions[name] = {"module": None, "ledger": {"cogs": [], "commands": []}}
        self._loading_extension = name
        try:
            module = importlib.import_module(module_name)
            setup = getattr(module, "setup")
            await setup(self)
        except Exception as exc:  # noqa: BLE001 - roll back and report
            self._rollback(name)
            raise ExtensionFailed(name, exc) from exc
        else:
            self._extensions[name]["module"] = module
        finally:
            self._loading_extension = None

    async def unload_extension(self, name: str, *, package: str | None = None) -> None:
        """Call ``teardown(bot)`` and remove everything the extension registered."""
        data = self._extensions.get(name)
        if data is None:
            raise ExtensionNotLoaded(f"extension {name!r} is not loaded")
        module = data["module"]
        teardown = getattr(module, "teardown", None) if module is not None else None
        if teardown is not None:
            await teardown(self)
        for cog in list(data["ledger"]["cogs"]):
            if cog.qualified_name in self.cogs:
                await self.remove_cog(cog.qualified_name)
        for command_obj in data["ledger"]["commands"]:
            if self.commands.get(command_obj.name) is command_obj:
                self.remove_command(command_obj.name)
        self._extensions.pop(name, None)
        self._purge(module)

    async def reload_extension(self, name: str, *, package: str | None = None) -> None:
        """Atomically unload and reload an extension.

        A failed reload restores the previously loaded cogs, commands and module and raises
        :class:`ExtensionFailed`.
        """
        data = self._extensions.get(name)
        if data is None:
            raise ExtensionNotLoaded(f"extension {name!r} is not loaded")
        old_cogs = list(data["ledger"]["cogs"])
        old_commands = list(data["ledger"]["commands"])
        old_module = data["module"]
        module_name = old_module.__name__ if old_module is not None else name
        await self.unload_extension(name, package=package)
        try:
            await self.load_extension(name, package=package)
        except ExtensionFailed as exc:
            for cog in old_cogs:
                if cog.qualified_name not in self.cogs:
                    await self.add_cog(cog)
            for command_obj in old_commands:
                if self.commands.get(command_obj.name) is None:
                    self.add_command(command_obj)
            if old_module is not None:
                sys.modules[module_name] = old_module
            self._extensions[name] = {
                "module": old_module,
                "ledger": {"cogs": old_cogs, "commands": old_commands},
            }
            raise exc

    def _rollback(self, name: str) -> None:
        data = self._extensions.pop(name, None)
        if data is None:
            return
        for cog in data["ledger"]["cogs"]:
            if cog.qualified_name in self.cogs:
                for command_obj in cog.get_commands():
                    if self.commands.get(command_obj.name) is command_obj:
                        self.remove_command(command_obj.name)
                for loop in cog.get_loops():
                    loop.cancel()
                self.events.unsubscribe_owner(cog)
                self.cogs.pop(cog.qualified_name, None)
        for command_obj in data["ledger"]["commands"]:
            if self.commands.get(command_obj.name) is command_obj:
                self.remove_command(command_obj.name)

    def _purge(self, module: Any) -> None:
        name = getattr(module, "__name__", None)
        if not name:
            return
        for key in [key for key in sys.modules if key == name or key.startswith(f"{name}.")]:
            sys.modules.pop(key, None)

    # ------------------------------------------------------------------ lookups
    def get_player(self, name: str) -> Any | None:
        """Find a tab-list player or tracked player entity by name."""
        lowered = name.lower()
        for info in self.players.values():
            if info.name and info.name.lower() == lowered:
                return info
        for entity in self.entities.all():
            if entity.name and entity.name.lower() == lowered:
                return entity
        return None

    @property
    def player_names(self) -> list[str]:
        """Every known player name, tab list first."""
        names = [info.name for info in self.players.values() if info.name]
        names.extend(entity.name for entity in self.entities.all() if entity.name)
        return sorted(set(names))
