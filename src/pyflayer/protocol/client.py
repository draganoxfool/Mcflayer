"""Protocol client: handshake -> login -> play.

This is the layer that turns a :class:`~pyflayer.protocol.connection.Connection` plus a packet
registry into a decoded packet stream. It owns the login handshake, optional encryption and
compression, and nothing about the game (ADR-3): no world, no events.

Examples:
    >>> async def join():
    ...     client = ProtocolClient("play.pika-network.net", username="Steve")
    ...     await client.connect()
    ...     async for packet in client.packets():
    ...         print(packet.name)
    ...     await client.close()
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.data.loader import McData
from pyflayer.errors import (
    ConnectionClosed,
    LoginRejected,
    MalformedPacket,
    ProtocolError,
    UnknownPacket,
    UnsupportedType,
)
from pyflayer.models.enums import ConnectionState
from pyflayer.models.text import ChatComponent
from pyflayer.protocol.auth.base import AuthProvider, Session
from pyflayer.protocol.auth.offline import OfflineAuth
from pyflayer.protocol.auth.session_join import server_hash
from pyflayer.protocol.connection import DEFAULT_PORT, Connection
from pyflayer.protocol.crypto import encrypt_rsa
from pyflayer.protocol.protodef import Packet
from pyflayer.protocol.registry import PacketRegistry
from pyflayer.protocol.state import StateMachine

__all__ = ["ProtocolClient"]

log = logging.getLogger("pyflayer.protocol.client")

NEXT_STATE_STATUS = 1
NEXT_STATE_LOGIN = 2


class ProtocolClient:
    """One Minecraft protocol connection.

    Args:
        host: Server hostname (SRV-resolved when the port is the default).
        username: Offline username, used when ``auth`` is not supplied.
        port: TCP port.
        version: Minecraft version or protocol number (defaults to 1.8.9).
        auth: Authentication provider; defaults to :class:`OfflineAuth`.
        use_srv: Resolve ``_minecraft._tcp`` records.
        clock: Injected clock.
        connect_timeout: TCP connect timeout.
        read_timeout: Per-frame read timeout (``None`` waits forever; keep-alives still arrive).
        use_compression: Legacy option; server-mandated compression is always applied.
    """

    __slots__ = (
        "auth",
        "clock",
        "compression_threshold",
        "connect_timeout",
        "connection",
        "encrypted",
        "host",
        "mc",
        "port",
        "read_timeout",
        "registry",
        "session",
        "skipped_packets",
        "state",
        "unknown_packet_ids",
        "use_compression",
        "use_srv",
        "version",
    )

    def __init__(
        self,
        host: str,
        username: str | None = None,
        *,
        port: int = DEFAULT_PORT,
        version: str = "1.8.9",
        auth: AuthProvider | None = None,
        use_srv: bool = True,
        clock: Clock | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float | None = None,
        use_compression: bool = True,
    ) -> None:
        if auth is None:
            if username is None:
                raise ValueError("username is required when no auth provider is given")
            auth = OfflineAuth(username)
        self.host = host
        self.port = port
        self.version = version
        self.auth = auth
        self.use_srv = use_srv
        self.clock = clock or MonotonicClock()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.use_compression = use_compression
        self.connection: Connection | None = None
        self.mc = McData.load(version)
        self.registry = PacketRegistry(self.mc)
        self.state = StateMachine()
        self.session: Session | None = None
        self.encrypted = False
        self.compression_threshold = -1
        self.skipped_packets = 0
        self.unknown_packet_ids: set[int] = set()

    # ------------------------------------------------------------------ properties
    @property
    def protocol(self) -> int:
        """Protocol number advertised in the handshake."""
        return self.mc.version.protocol

    @property
    def connected(self) -> bool:
        """True when the TCP connection is open and not closed."""
        return self.connection is not None and not self.state.closed

    # ------------------------------------------------------------------ lifecycle
    async def connect(self, *, host: str | None = None, port: int | None = None) -> Session:
        """Open the socket and complete the login, leaving the client in Play.

        Args:
            host: Override the hostname (for SRV reconnects).
            port: Override the port.

        Returns:
            The authenticated session.

        Raises:
            ConnectionClosed: On network failure.
            LoginRejected: When the server refuses the login.
            AuthError: When authentication or the session-server join fails.
            StateError: On an illegal state transition (a library bug).
        """
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        self.connection = await Connection.open(
            self.host,
            self.port,
            use_srv=self.use_srv,
            connect_timeout=self.connect_timeout,
            read_timeout=self.read_timeout,
            clock=self.clock,
        )
        self.state = StateMachine()
        try:
            await self._send(
                "handshaking",
                "toServer",
                "set_protocol",
                {
                    "protocolVersion": self.protocol,
                    "serverHost": self.host,
                    "serverPort": self.port,
                    "nextState": NEXT_STATE_LOGIN,
                },
            )
            self.state.transition(ConnectionState.LOGIN)
            self.session = await self.auth.login()
            log.debug("logging in as %s (%s)", self.session.username, self.session.uuid)
            await self._send(
                "login", "toServer", "login_start", {"username": self.session.username}
            )
            await self._login_loop()
            self.state.transition(ConnectionState.PLAY)
        except BaseException:
            # A rejected or interrupted login must not leave the socket open.
            await self.close()
            raise
        return self.session

    async def close(self) -> None:
        """Close the connection. Idempotent."""
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
        self.state.close()

    async def __aenter__(self) -> ProtocolClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # ------------------------------------------------------------------ send
    async def send_packet(self, name: str, fields: dict[str, object] | None = None) -> None:
        """Encode and send a Play packet by name."""
        if self.state.state is not ConnectionState.PLAY:
            raise ProtocolError(
                "cannot send a play packet outside play",
                state=str(self.state.state),
                packet=name,
            )
        await self._send("play", "toServer", name, fields or {})

    async def send_chat(self, message: str) -> None:
        """Send a chat message or ``/command`` (1.8 unsigned chat)."""
        await self.send_packet("chat", {"message": message})

    # ------------------------------------------------------------------ receive
    async def packets(self) -> AsyncIterator[Packet]:
        """Yield decoded Play packets until the connection closes.

        Unknown ids and packets whose codec is not implemented yet (entity metadata, chunk data
        until M3) are counted in ``skipped_packets`` and dropped; game-state packets are never
        fatal. Compression changes announced in Play are applied and not yielded.
        """
        while self.state.state is ConnectionState.PLAY:
            packet = await self.read_packet()
            if packet.name == "set_compression":
                threshold = int(packet.fields.get("threshold", -1))
                self.set_compression(threshold)
                continue
            if packet.name.startswith(("unknown_0x", "unsupported_")):
                continue
            yield packet

    async def read_packet(self) -> Packet:
        """Read exactly one decoded Play packet."""
        if self.connection is None:
            raise ConnectionClosed("connection is not open")
        payload = await self.connection.read_payload()
        try:
            packet = self.registry.decode("play", "toClient", payload, strict=False)
        except UnknownPacket as exc:
            self.skipped_packets += 1
            self.unknown_packet_ids.add(exc.packet_id)
            log.debug("skipping unknown play packet id 0x%02x", exc.packet_id)
            return Packet(
                name=f"unknown_0x{exc.packet_id:02x}",
                fields={"packet_id": exc.packet_id, "raw": exc.raw},
                state="play",
                direction="toClient",
                raw_len=len(payload),
            )
        except UnsupportedType as exc:
            self.skipped_packets += 1
            log.debug("skipping packet without a codec: %s", exc)
            return Packet(
                name=f"unsupported_{exc.fields.get('type_name', 'packet')}",
                fields={},
                state="play",
                direction="toClient",
                raw_len=len(payload),
            )
        return packet

    # ------------------------------------------------------------------ login internals
    async def _login_loop(self) -> None:
        while True:
            payload = await self._read_login_payload()
            try:
                packet = self.registry.decode("login", "toClient", payload, strict=False)
            except UnknownPacket as exc:
                raise ProtocolError(
                    "unknown login packet",
                    packet_id=exc.packet_id,
                    raw=exc.raw[:64],
                ) from exc
            name = packet.name
            if name == "disconnect":
                reason = ChatComponent.parse(packet.fields.get("reason", ""))
                raise LoginRejected("server rejected the login", reason=reason)
            if name == "encryption_begin":
                await self._enable_encryption(packet)
                continue
            if name == "compress":
                threshold = int(packet.fields.get("threshold", -1))
                self.set_compression(threshold)
                log.debug("compression enabled (threshold=%d)", threshold)
                continue
            if name == "success":
                assert self.session is not None
                username = str(packet.fields.get("username") or self.session.username)
                uuid = str(packet.fields.get("uuid") or self.session.uuid)
                self.session = Session(
                    username=username,
                    uuid=uuid,
                    access_token=self.session.access_token,
                    xuid=self.session.xuid,
                )
                return
            log.debug("ignoring login packet %s", name)

    async def _read_login_payload(self) -> bytes:
        if self.connection is None:
            raise ConnectionClosed("connection is not open")
        return await self.connection.read_payload()

    async def _enable_encryption(self, packet: Packet) -> None:
        assert self.session is not None
        public_key = bytes(packet.fields["publicKey"])
        verify_token = bytes(packet.fields["verifyToken"])
        server_id = str(packet.fields.get("serverId", ""))
        shared_secret = os.urandom(16)
        digest = server_hash(server_id, shared_secret, public_key)
        # The session server must accept the join before the response is sent.
        await self.auth.join(self.session, server_hash=digest)
        encrypted_secret = encrypt_rsa(public_key, shared_secret)
        encrypted_token = encrypt_rsa(public_key, verify_token)
        # Response goes out in the clear; encryption starts at the next frame boundary.
        await self._send(
            "login",
            "toServer",
            "encryption_begin",
            {"sharedSecret": encrypted_secret, "verifyToken": encrypted_token},
        )
        if self.connection is None:
            raise ConnectionClosed("connection closed during encryption handshake")
        self.connection.enable_encryption(shared_secret)
        self.encrypted = True
        log.debug("encryption enabled")

    def set_compression(self, threshold: int) -> None:
        """Apply a compression threshold to the connection codec."""
        self.compression_threshold = threshold
        if self.connection is not None:
            self.connection.set_compression(threshold)

    async def _send(
        self,
        state: str,
        direction: str,
        name: str,
        fields: dict[str, object],
    ) -> None:
        if self.connection is None:
            raise ConnectionClosed("connection is not open")
        payload = self.registry.encode(state, direction, name, fields)
        await self.connection.write_payload(payload)

    # ------------------------------------------------------------------ misc
    def packet_id(self, state: str, direction: str, name: str) -> int:
        """Packet id for a name (debugging aid)."""
        return self.registry.packet_id(state, direction, name)

    def __repr__(self) -> str:
        return (
            f"ProtocolClient(host={self.host!r}, port={self.port}, "
            f"state={self.state.state.value!r})"
        )


def decode_play_packet(registry: PacketRegistry, payload: bytes) -> Packet:
    """Decode one Play packet body (helper for tools and tests)."""
    try:
        return registry.decode("play", "toClient", payload, strict=False)
    except MalformedPacket:
        raise
