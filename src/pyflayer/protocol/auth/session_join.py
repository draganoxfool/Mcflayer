"""Minecraft session server join and the server-hash digest.

After the client and server agree on a shared secret, an online-mode client proves ownership by
posting a signed SHA-1 of ``serverId + sharedSecret + publicKey`` to
``sessionserver.mojang.com/session/minecraft/join``. Java signs the digest as a two's-complement
big integer, so approximately half of all hashes are prefixed with ``-``.

Examples:
    >>> server_hash("", bytes(16), b"key")  # doctest: +SKIP
    '...'
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from pyflayer.errors import AuthError
from pyflayer.protocol.auth.base import Session

__all__ = ["SESSIONSERVER_JOIN", "server_hash", "join_session"]

SESSIONSERVER_JOIN = "https://sessionserver.mojang.com/session/minecraft/join"


def server_hash(server_id: str, shared_secret: bytes, public_key: bytes) -> str:
    """Return Minecraft's signed SHA-1 hex digest.

    Args:
        server_id: The ``serverId`` string from the encryption request (usually ``""``).
        shared_secret: The 16-byte AES secret generated for this connection.
        public_key: DER-encoded server public key from the encryption request.

    Returns:
        Lowercase hex, prefixed with ``-`` when the digest is negative as a signed big integer.
    """
    digest = hashlib.sha1(server_id.encode("utf-8") + shared_secret + public_key).digest()
    value = int.from_bytes(digest, "big", signed=True)
    return format(value, "x")


async def join_session(
    session: Session,
    digest: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 15.0,
) -> None:
    """Ask the Mojang session server to register a join.

    Args:
        session: Online session with an access token.
        digest: Value returned by :func:`server_hash`.
        client: Optional shared HTTP client.
        timeout: Request timeout in seconds.

    Raises:
        AuthError: When the session is offline or the session server rejects the join.
    """
    if not session.access_token:
        raise AuthError("cannot join a session server with an offline session", username=session.username)
    payload: dict[str, Any] = {
        "accessToken": session.access_token,
        "selectedProfile": session.uuid_no_dashes,
        "serverId": digest,
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=timeout) as own_client:
                response = await own_client.post(SESSIONSERVER_JOIN, json=payload)
        else:
            response = await client.post(SESSIONSERVER_JOIN, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise AuthError("session server request failed", reason=str(exc)) from exc
    if response.status_code not in (200, 204):
        raise AuthError(
            "session server rejected the join",
            status=response.status_code,
            body=response.text[:200],
        )
