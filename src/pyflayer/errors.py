"""Exception tree for PyFlayer.

Every error raised by library code derives from :class:`PyFlayerError` (ADR-10). Errors carry
structured fields so callers can react without parsing strings.

Examples:
    >>> try:
    ...     raise MalformedPacket("bad varint", offset=3)
    ... except ProtocolError as exc:
    ...     print(exc.offset)
    3
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "ActionBusy",
    "ActionCancelled",
    "ActionError",
    "ActionFailed",
    "ActionPreempted",
    "AuthError",
    "ChunkNotLoaded",
    "CompressionError",
    "ConnectionClosed",
    "DataError",
    "ExtensionAlreadyLoaded",
    "ExtensionError",
    "ExtensionFailed",
    "ExtensionNotLoaded",
    "FramingError",
    "KickedError",
    "LeaseRevoked",
    "LoginRejected",
    "MalformedPacket",
    "MissingRegistryEntry",
    "NoPath",
    "OutOfWorldBounds",
    "PathError",
    "PathTimeout",
    "ProtocolError",
    "PyFlayerError",
    "StateError",
    "UnknownPacket",
    "UnsupportedType",
    "UnsupportedVersion",
    "WorldError",
]


class PyFlayerError(Exception):
    """Base class for every error raised by PyFlayer."""

    def __init__(self, message: str = "", **fields: Any) -> None:
        super().__init__(message)
        self.message: Final = message
        self.fields: Final[dict[str, Any]] = fields

    def __str__(self) -> str:
        if not self.fields:
            return self.message
        details = ", ".join(f"{k}={v!r}" for k, v in sorted(self.fields.items()))
        return f"{self.message} ({details})" if self.message else details


# --------------------------------------------------------------------------- protocol


class ProtocolError(PyFlayerError):
    """Base class for framing, codec and state-machine errors."""


class MalformedPacket(ProtocolError):
    """Bytes did not match the wire format."""

    def __init__(
        self,
        message: str = "malformed packet",
        *,
        offset: int | None = None,
        packet: str | None = None,
        **fields: Any,
    ) -> None:
        super().__init__(message, offset=offset, packet=packet, **fields)


class UnknownPacket(ProtocolError):
    """A packet id has no registered codec.

    The raw payload is retained so callers may log or skip it; M1 never treats it as fatal.
    """

    def __init__(self, message: str, *, packet_id: int, raw: bytes = b"", **fields: Any) -> None:
        super().__init__(message, packet_id=packet_id, raw=raw, **fields)
        self.packet_id = packet_id
        self.raw = raw


class FramingError(ProtocolError):
    """A frame length prefix or frame body was invalid."""


class CompressionError(ProtocolError):
    """Compressed payload did not match its declared uncompressed size or was a zlib bomb."""


class StateError(ProtocolError):
    """An illegal connection-state transition was attempted."""

    def __init__(
        self, message: str, *, current: object = None, target: object = None, **kwargs: Any
    ) -> None:
        super().__init__(message, current=current, target=target, **kwargs)


class UnsupportedVersion(ProtocolError):
    """No data is available for the requested Minecraft version."""


class UnsupportedType(ProtocolError):
    """The protodef compiler met a type it does not implement (yet)."""

    def __init__(self, message: str, *, type_name: str | None = None, **fields: Any) -> None:
        super().__init__(message, type_name=type_name, **fields)


class ConnectionClosed(PyFlayerError):
    """The peer closed the connection, possibly mid-frame."""

    def __init__(
        self,
        message: str = "connection closed",
        *,
        bytes_consumed: int | None = None,
        expected: int | None = None,
        **fields: Any,
    ) -> None:
        super().__init__(message, bytes_consumed=bytes_consumed, expected=expected, **fields)


# --------------------------------------------------------------------------- auth / login


class AuthError(PyFlayerError):
    """Authentication failed (offline name, Microsoft device flow, XSTS, sessionserver)."""


class LoginRejected(PyFlayerError):
    """The server refused the login and supplied a reason component."""

    def __init__(
        self, message: str = "login rejected", *, reason: object = None, **fields: Any
    ) -> None:
        super().__init__(message, reason=reason, **fields)


class KickedError(PyFlayerError):
    """The server kicked the connected client."""

    def __init__(self, message: str = "kicked", *, reason: object = None, **fields: Any) -> None:
        super().__init__(message, reason=reason, **fields)


# --------------------------------------------------------------------------- data / world


class DataError(PyFlayerError):
    """minecraft-data could not be loaded or was inconsistent."""


class MissingRegistryEntry(DataError):
    """A registry lookup failed."""

    def __init__(self, message: str, *, registry: str, key: object, **fields: Any) -> None:
        super().__init__(message, registry=registry, key=key, **fields)


class WorldError(PyFlayerError):
    """Base class for world/chunk errors."""


class ChunkNotLoaded(WorldError):
    """A block was requested in a chunk that is not loaded."""

    def __init__(
        self, message: str = "chunk not loaded", *, pos: object = None, **fields: Any
    ) -> None:
        super().__init__(message, pos=pos, **fields)


class OutOfWorldBounds(WorldError):
    """A coordinate lies outside the dimension's vertical range."""


# --------------------------------------------------------------------------- actions / paths


class ActionError(PyFlayerError):
    """Base class for action-scheduler errors."""


class ActionBusy(ActionError):
    """A conflicting action holds the requested resources."""


class ActionPreempted(ActionError):
    """A higher-priority action took over the lease."""


class ActionCancelled(ActionError):
    """The action's handle was cancelled by user code."""


class ActionFailed(ActionError):
    """The action raised while running."""


class LeaseRevoked(ActionError):
    """A revoked lease was used to write controls."""


class PathError(PyFlayerError):
    """Base class for pathfinder errors."""


class NoPath(PathError):
    """No path exists to the goal (a best partial path may be attached)."""

    def __init__(self, message: str = "no path", *, partial: object = None, **fields: Any) -> None:
        super().__init__(message, partial=partial, **fields)


class PathTimeout(PathError):
    """The search budget was exhausted before a path was found."""


# --------------------------------------------------------------------------- extensions


class ExtensionError(PyFlayerError):
    """Base class for ext loader errors."""


class ExtensionNotLoaded(ExtensionError):
    """The extension is not currently loaded."""


class ExtensionAlreadyLoaded(ExtensionError):
    """The extension is already loaded."""


class ExtensionFailed(ExtensionError):
    """Loading, unloading or reloading an extension failed (state was rolled back)."""
