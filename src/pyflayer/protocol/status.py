"""Server List Ping (SLP) client.

Works with 1.7+ modern status (1.8.9 included). The handshake is sent in the ``handshaking`` state,
then a status request, a status response (JSON), and a ping/pong for latency.

CLI::

    python -m pyflayer.protocol.status play.example.org
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from dataclasses import dataclass, field

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.data.versions import protocol_for
from pyflayer.errors import MalformedPacket, ProtocolError
from pyflayer.models.text import ChatComponent
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.connection import DEFAULT_PORT, Connection

__all__ = ["ServerStatus", "StatusPlayer", "main", "ping"]


@dataclass(frozen=True, slots=True)
class StatusPlayer:
    """One player in the optional sample list."""

    name: str
    uuid: str | None = None


@dataclass(frozen=True, slots=True)
class ServerStatus:
    """Typed result of a server list ping.

    Attributes:
        version_name: Human-readable version (``"1.8.9"``).
        protocol: Protocol number advertised by the server.
        max_players: Advertised player cap.
        online_players: Advertised online count.
        description: MOTD as a chat component.
        sample: Optional player sample.
        favicon: Raw ``data:image/png;base64,...`` string, or ``None``.
        latency_ms: Round-trip ping in milliseconds.
        raw: The original JSON mapping.
    """

    version_name: str
    protocol: int
    max_players: int
    online_players: int
    description: ChatComponent
    sample: tuple[StatusPlayer, ...] = ()
    favicon: str | None = None
    latency_ms: float = 0.0
    raw: dict[str, object] = field(default_factory=dict, compare=False, repr=False)

    @property
    def motd(self) -> str:
        """The MOTD flattened to plain text."""
        return self.description.plain_text()

    @property
    def favicon_png(self) -> bytes | None:
        """Decode the favicon data URL, or ``None`` when absent/invalid."""
        if not self.favicon or "," not in self.favicon:
            return None
        try:
            return base64.b64decode(self.favicon.split(",", 1)[1])
        except (ValueError, TypeError):
            return None


def _handshake(host: str, port: int, protocol: int, next_state: int) -> bytes:
    writer = PacketWriter()
    writer.write_varint(0x00)
    writer.write_varint(protocol)
    writer.write_string(host)
    writer.write_u16(port)
    writer.write_varint(next_state)
    return writer.to_bytes()


def _status_request() -> bytes:
    return PacketWriter().to_bytes() + b"\x00"


def _ping_payload(value: int) -> bytes:
    writer = PacketWriter()
    writer.write_varint(0x01)
    writer.write_i64(value)
    return writer.to_bytes()


def _as_int(value: object, default: int = 0) -> int:
    """Coerce an optional status field, falling back for malformed values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_status_json(payload: str | bytes, *, latency_ms: float = 0.0) -> ServerStatus:
    """Parse the JSON status response. Malformed optional fields degrade gracefully."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedPacket("status response is not valid JSON", reason=str(exc)) from exc
    if not isinstance(data, dict):
        raise MalformedPacket("status response must be a JSON object")
    version = data.get("version") if isinstance(data.get("version"), dict) else {}
    players = data.get("players") if isinstance(data.get("players"), dict) else {}
    sample_raw = players.get("sample")
    sample: list[StatusPlayer] = []
    if isinstance(sample_raw, list):
        for entry in sample_raw:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                uuid = entry.get("id")
                sample.append(StatusPlayer(entry["name"], uuid if isinstance(uuid, str) else None))
    description = data.get("description", "")
    favicon = data.get("favicon")
    name = version.get("name")
    return ServerStatus(
        version_name=name if isinstance(name, str) else "unknown",
        protocol=_as_int(version.get("protocol")),
        max_players=_as_int(players.get("max")),
        online_players=_as_int(players.get("online")),
        description=ChatComponent.parse(description),
        sample=tuple(sample),
        favicon=favicon if isinstance(favicon, str) else None,
        latency_ms=latency_ms,
        raw=data,
    )


async def ping(
    host: str,
    port: int = DEFAULT_PORT,
    *,
    protocol: str | int = "1.8.9",
    use_srv: bool = True,
    timeout: float = 5.0,  # noqa: ASYNC109 - public overall timeout option
    clock: Clock | None = None,
) -> ServerStatus:
    """Ping a server and return its status.

    Args:
        host: Hostname or IP.
        port: Port (SRV is used when the port is the default).
        protocol: Version string or protocol number to advertise.
        use_srv: Resolve ``_minecraft._tcp`` records.
        timeout: Overall handshake/read timeout in seconds.
        clock: Injected clock for deterministic latency in tests.

    Raises:
        ConnectionClosed: On network failure.
        MalformedPacket: On a malformed response.
        ProtocolError: On an unexpected packet id.
    """
    clock = clock or MonotonicClock()
    protocol_number = protocol_for(protocol)
    async with asyncio.timeout(timeout):
        conn = await Connection.open(host, port, use_srv=use_srv, clock=clock)
        try:
            await conn.write_payload(_handshake(host, port, protocol_number, 1))
            await conn.write_payload(_status_request())
            response = PacketReader(await conn.read_payload())
            packet_id = response.read_varint()
            if packet_id != 0x00:
                raise ProtocolError("unexpected status packet", packet_id=packet_id)
            status = parse_status_json(response.read_string(32767))
            started = clock.monotonic()
            await conn.write_payload(_ping_payload(0x0F00D))
            pong = PacketReader(await conn.read_payload())
            pong_id = pong.read_varint()
            if pong_id != 0x01:
                raise ProtocolError("unexpected pong packet", packet_id=pong_id)
            pong.read_i64()
            latency_ms = (clock.monotonic() - started) * 1000.0
            return ServerStatus(
                version_name=status.version_name,
                protocol=status.protocol,
                max_players=status.max_players,
                online_players=status.online_players,
                description=status.description,
                sample=status.sample,
                favicon=status.favicon,
                latency_ms=latency_ms,
                raw=status.raw,
            )
        finally:
            await conn.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Ping a Minecraft Java server (SLP)")
    parser.add_argument("host", help="hostname or IP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--version", default="1.8.9", help="version string or protocol number")
    parser.add_argument("--no-srv", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        status = asyncio.run(
            ping(
                args.host,
                args.port,
                protocol=args.version,
                use_srv=not args.no_srv,
                timeout=args.timeout,
            )
        )
    except (ProtocolError, OSError) as exc:
        print(f"ping failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.host}:{args.port}")
    print(f"  version : {status.version_name} (protocol {status.protocol})")
    print(f"  players : {status.online_players}/{status.max_players}")
    print(f"  latency : {status.latency_ms:.1f} ms")
    print(f"  motd    : {status.motd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
