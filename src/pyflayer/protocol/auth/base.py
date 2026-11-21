"""Authentication provider interface.

A provider supplies the identity used for Login Start and, for online mode, proves ownership of
that identity to the session server after the server sends its encryption request.

Examples:
    >>> from pyflayer.protocol.auth.offline import OfflineAuth
    >>> OfflineAuth.derive_uuid("Notch")
    'b50ad385-829d-3141-a216-7e7d7539ba7f'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["Session", "AuthProvider", "StaticAuth"]


@dataclass(frozen=True, slots=True)
class Session:
    """A player identity used for one login.

    Attributes:
        username: In-game name sent in Login Start.
        uuid: Canonical dashed UUID string.
        access_token: Minecraft services token for online mode, or ``None`` for offline mode.
        xuid: Xbox user id, when known.
    """

    username: str
    uuid: str
    access_token: str | None = None
    xuid: str | None = None

    @property
    def online(self) -> bool:
        """True when the session can be verified by the Mojang session server."""
        return self.access_token is not None

    @property
    def uuid_no_dashes(self) -> str:
        """UUID without dashes (the sessionserver profile id format)."""
        return self.uuid.replace("-", "")


class AuthProvider(Protocol):
    """Identity provider used by :class:`~pyflayer.protocol.client.ProtocolClient`."""

    async def login(self) -> Session:
        """Obtain (or refresh) a session."""
        ...

    async def join(self, session: Session, *, server_hash: str) -> None:
        """Join the session server with a server hash.

        Offline providers do nothing; online providers call
        ``sessionserver.mojang.com/session/minecraft/join``.
        """
        ...


class StaticAuth:
    """Auth provider that returns a pre-obtained session.

    Useful for tests, token caches and callers that manage Microsoft auth themselves.

    Args:
        session: The session to return.
        online_join: When true, :meth:`join` calls the Mojang session server.
    """

    __slots__ = ("_session", "_online_join")

    def __init__(self, session: Session, *, online_join: bool = False) -> None:
        self._session = session
        self._online_join = online_join

    async def login(self) -> Session:
        return self._session

    async def join(self, session: Session, *, server_hash: str) -> None:
        if self._online_join:
            from pyflayer.protocol.auth.session_join import join_session

            await join_session(session, server_hash)
