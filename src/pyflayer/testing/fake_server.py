"""In-process Minecraft server for tests.

Implements the 1.8.9 handshake, optional RSA/AES-CFB8 encryption, optional compression, Login
Success, Join Game, keep-alive echo, chat echo and respawn. It deliberately understands only what
the bot needs, so tests do not require Docker or network access.

Examples:
    >>> async def run():
    ...     async with FakeServer(compression=64, encryption=True) as server:
    ...         client = ProtocolClient("127.0.0.1", "Steve", port=server.port, use_srv=False)
    ...         await client.connect()
    ...         await client.close()
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from pyflayer.data.loader import McData
from pyflayer.errors import ConnectionClosed
from pyflayer.protocol.auth.offline import offline_uuid
from pyflayer.protocol.connection import Connection
from pyflayer.protocol.protodef import Packet
from pyflayer.protocol.registry import PacketRegistry

__all__ = ["FakeServer"]

JOIN_FIELDS: dict[str, Any] = {
    "entityId": 1,
    "gameMode": 1,
    "dimension": 0,
    "difficulty": 0,
    "maxPlayers": 20,
    "levelType": "flat",
    "reducedDebugInfo": False,
}

SPAWN_FIELDS: dict[str, Any] = {
    "x": 0.5,
    "y": 64.0,
    "z": 0.5,
    "yaw": 0.0,
    "pitch": 0.0,
    "flags": 0,
}


class FakeServer:
    """A scriptable offline-mode server.

    Args:
        version: Minecraft version to serve (data must be vendored).
        compression: Threshold for Set Compression, or ``-1`` to leave it off.
        encryption: Require the RSA/AES encryption handshake.
        kick_after_join: Send a kick with ``kick_reason`` right after Join Game.
        kick_reason: JSON chat component used for the kick.
        join_delay: Seconds to wait before Join Game (keep-alive ordering tests).
        host: Bind address.
        port: Bind port (0 picks a free one).
    """

    def __init__(
        self,
        *,
        version: str = "1.8.9",
        compression: int = -1,
        encryption: bool = False,
        kick_after_join: bool = False,
        kick_reason: str = '{"text":"test kick"}',
        reject_login: str | None = None,
        join_delay: float = 0.0,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.version = version
        self.compression = compression
        self.encryption = encryption
        self.kick_after_join = kick_after_join
        self.kick_reason = kick_reason
        self.reject_login = reject_login
        self.join_delay = join_delay
        self.host = host
        self.port = port
        self.mc = McData.load(version)
        self.registry = PacketRegistry(self.mc)
        self.received: list[Packet] = []
        self.chats: list[str] = []
        self.usernames: list[str] = []
        self.settings: dict[str, Any] | None = None
        self.keep_alives: list[int] = []
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._connections: list[Connection] = []

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> FakeServer:
        """Start listening and return ``self``."""
        self._server = await asyncio.start_server(self._accept, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        """Stop the listener and close every connection."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for conn in self._connections:
            await conn.close()
        self._connections.clear()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def __aenter__(self) -> FakeServer:
        return await self.start()

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------ helpers
    def encode(self, state: str, direction: str, name: str, fields: dict[str, Any]) -> bytes:
        """Encode a packet with this server's registry."""
        return self.registry.encode(state, direction, name, fields)

    def decode(self, state: str, direction: str, payload: bytes) -> Packet:
        """Decode a packet with this server's registry."""
        return self.registry.decode(state, direction, payload)

    def send_play(self, name: str, fields: dict[str, Any] | None = None) -> None:
        """Send a Play packet to every live connection (test hook)."""
        payload = self.encode("play", "toClient", name, fields or {})
        for conn in list(self._connections):
            task = asyncio.ensure_future(conn.write_payload(payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def announce(self, text: str) -> None:
        """Send a server chat line (test hook)."""
        self.send_play("chat", {"message": json.dumps({"text": text}), "position": 1})

    # ------------------------------------------------------------------ connection
    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = Connection(reader, writer, clock=None)
        self._connections.append(conn)
        try:
            await self._serve(conn)
        except (ConnectionClosed, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            await conn.close()
            if conn in self._connections:
                self._connections.remove(conn)

    async def _serve(self, conn: Connection) -> None:
        handshake = self.decode("handshaking", "toServer", await conn.read_payload())
        if int(handshake.fields.get("nextState", 0)) != 2:
            return
        login = self.decode("login", "toServer", await conn.read_payload())
        username = str(login.fields.get("username", "Bot"))
        self.usernames.append(username)
        if self.reject_login is not None:
            await conn.write_payload(
                self.encode(
                    "login", "toClient", "disconnect", {"reason": self.reject_login}
                )
            )
            return

        if self.encryption:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
            public_der = private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            verify_token = os.urandom(4)
            await conn.write_payload(
                self.encode(
                    "login",
                    "toClient",
                    "encryption_begin",
                    {"serverId": "", "publicKey": public_der, "verifyToken": verify_token},
                )
            )
            response = self.decode("login", "toServer", await conn.read_payload())
            secret = private_key.decrypt(
                bytes(response.fields["sharedSecret"]), padding.PKCS1v15()
            )
            token = private_key.decrypt(
                bytes(response.fields["verifyToken"]), padding.PKCS1v15()
            )
            if token != verify_token:
                raise ConnectionClosed("verify token mismatch")
            conn.enable_encryption(secret)

        if self.compression >= 0:
            await conn.write_payload(
                self.encode("login", "toClient", "compress", {"threshold": self.compression})
            )
            conn.set_compression(self.compression)

        await conn.write_payload(
            self.encode(
                "login",
                "toClient",
                "success",
                {"uuid": offline_uuid(username), "username": username},
            )
        )

        await conn.write_payload(self.encode("play", "toClient", "login", JOIN_FIELDS))
        await conn.write_payload(
            self.encode(
                "play",
                "toClient",
                "spawn_position",
                {"location": {"x": 0, "y": 64, "z": 0}},
            )
        )
        if self.join_delay:
            await asyncio.sleep(self.join_delay)
        await conn.write_payload(self.encode("play", "toClient", "position", SPAWN_FIELDS))

        if self.kick_after_join:
            await conn.write_payload(
                self.encode(
                    "play", "toClient", "kick_disconnect", {"reason": self.kick_reason}
                )
            )
            return

        while True:
            payload = await conn.read_payload()
            packet = self.decode("play", "toServer", payload)
            self.received.append(packet)
            if packet.name == "keep_alive":
                identifier = int(packet.fields.get("keepAliveId", 0))
                self.keep_alives.append(identifier)
                await conn.write_payload(
                    self.encode("play", "toClient", "keep_alive", {"keepAliveId": identifier})
                )
            elif packet.name == "chat":
                message = str(packet.fields.get("message", ""))
                self.chats.append(message)
                reply = {"text": f"<{username}> {message}"}
                await conn.write_payload(
                    self.encode(
                        "play",
                        "toClient",
                        "chat",
                        {"message": json.dumps(reply), "position": 0},
                    )
                )
            elif packet.name == "settings":
                self.settings = dict(packet.fields)
            elif packet.name == "client_command" and packet.fields.get(
                "payload"
            ) == "perform_respawn":
                await conn.write_payload(
                    self.encode(
                        "play",
                        "toClient",
                        "respawn",
                        {"dimension": 0, "difficulty": 0, "gamemode": 1, "levelType": "flat"},
                    )
                )
                await conn.write_payload(
                    self.encode("play", "toClient", "position", SPAWN_FIELDS)
                )
