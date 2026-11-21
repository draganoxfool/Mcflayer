"""Offline-mode authentication.

Cracked/offline servers (including PikaNetwork) accept any name and derive the UUID with
``UUIDv3("OfflinePlayer:<name>")``, exactly like the vanilla server does. No session-server call is
made because the server never sends an encryption request for these players.

Examples:
    >>> OfflineAuth.derive_uuid("Notch")
    'b50ad385-829d-3141-a216-7e7d7539ba7f'
"""

from __future__ import annotations

import hashlib
import uuid

from pyflayer.errors import AuthError
from pyflayer.protocol.auth.base import Session

__all__ = ["OfflineAuth", "offline_uuid", "validate_username"]

MAX_USERNAME_CHARS = 16
_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def validate_username(username: str) -> str:
    """Validate a Minecraft username.

    Raises:
        AuthError: When the name is empty, too long, or contains characters vanilla rejects.
    """
    if not username:
        raise AuthError("username must not be empty")
    if len(username) > MAX_USERNAME_CHARS:
        raise AuthError(
            "username is longer than 16 characters",
            username=username,
            length=len(username),
        )
    invalid = sorted({char for char in username if char not in _ALLOWED})
    if invalid:
        raise AuthError(
            "username contains characters vanilla does not allow",
            username=username,
            invalid="".join(invalid),
        )
    return username


def offline_uuid(username: str) -> str:
    """Derive the offline-mode UUID for a username (UUIDv3 over ``OfflinePlayer:<name>``)."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode(), usedforsecurity=False).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(digest)))


class OfflineAuth:
    """Auth provider for offline-mode servers.

    Args:
        username: Player name to send in Login Start.
    """

    __slots__ = ("username", "_session")

    def __init__(self, username: str) -> None:
        self.username = validate_username(username)
        self._session = Session(self.username, offline_uuid(self.username))

    @staticmethod
    def derive_uuid(username: str) -> str:
        """Public helper mirroring the server-side UUID derivation."""
        return offline_uuid(username)

    async def login(self) -> Session:
        return self._session

    async def join(self, session: Session, *, server_hash: str) -> None:
        """Offline servers do not verify sessions; intentionally a no-op."""
        del session, server_hash
