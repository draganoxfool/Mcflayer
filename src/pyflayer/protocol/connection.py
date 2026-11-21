"""Async TCP connection with Minecraft framing, optional encryption and SRV resolution.

The connection owns one asyncio stream pair. Reads use ``readexactly`` so fragmented 1-byte reads
work. Writes are serialized by a lock and use ``drain()`` for backpressure.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import suppress
from dataclasses import dataclass

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.errors import ConnectionClosed, FramingError
from pyflayer.protocol.crypto import CipherPair
from pyflayer.protocol.framing import MAX_FRAME, FrameCodec
from pyflayer.protocol.varint import decode_varint, encode_varint

__all__ = ["Connection", "ResolvedAddress", "resolve_address"]

SRV_PREFIX = "_minecraft._tcp."
DEFAULT_PORT = 25565


@dataclass(frozen=True, slots=True)
class ResolvedAddress:
    """Result of SRV resolution."""

    host: str
    port: int
    srv: bool = False


async def resolve_address(
    host: str,
    port: int = DEFAULT_PORT,
    *,
    timeout: float = 3.0,  # noqa: ASYNC109 - public DNS timeout option
) -> ResolvedAddress:
    """Resolve ``_minecraft._tcp.<host>`` to ``(host, port)``, falling back to ``host:port``."""
    if port != DEFAULT_PORT:
        return ResolvedAddress(host, port)

    def _lookup() -> ResolvedAddress:
        try:
            import dns.resolver  # type: ignore[import-untyped]

            resolver = dns.resolver.Resolver()
            resolver.lifetime = timeout
            answers = resolver.resolve(f"{SRV_PREFIX}{host}", "SRV")
            records = sorted(
                answers,
                key=lambda answer: (answer.priority, -answer.weight),
            )
            if records:
                target = str(records[0].target).rstrip(".")
                return ResolvedAddress(target or host, int(records[0].port), True)
        except Exception:
            pass
        return ResolvedAddress(host, port, False)

    try:
        async with asyncio.timeout(timeout + 1.0):
            return await asyncio.to_thread(_lookup)
    except TimeoutError:
        return ResolvedAddress(host, port, False)


class Connection:
    """One Minecraft TCP connection."""

    __slots__ = (
        "_cipher",
        "_codec",
        "_read_timeout",
        "_reader",
        "_write_lock",
        "_writer",
        "clock",
        "host",
        "port",
    )

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        host: str = "",
        port: int = DEFAULT_PORT,
        codec: FrameCodec | None = None,
        clock: Clock | None = None,
        read_timeout: float | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._codec = codec or FrameCodec()
        self._cipher: CipherPair | None = None
        self._write_lock = asyncio.Lock()
        self._read_timeout = read_timeout
        self.clock = clock or MonotonicClock()
        self.host = host
        self.port = port

    @classmethod
    async def open(
        cls,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        use_srv: bool = True,
        connect_timeout: float = 10.0,
        read_timeout: float | None = None,
        clock: Clock | None = None,
    ) -> Connection:
        """Connect to a server, resolving SRV when ``use_srv`` is true."""
        resolved = await resolve_address(host, port) if use_srv else ResolvedAddress(host, port)
        try:
            async with asyncio.timeout(connect_timeout):
                reader, writer = await asyncio.open_connection(
                    resolved.host, resolved.port, limit=MAX_FRAME + 32
                )
        except (OSError, TimeoutError) as exc:
            raise ConnectionClosed(
                f"failed to connect to {resolved.host}:{resolved.port}", reason=str(exc)
            ) from exc
        sock = writer.get_extra_info("socket")
        if isinstance(sock, socket.socket):
            with suppress(OSError):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn = cls(reader, writer, host=resolved.host, port=resolved.port, clock=clock)
        conn._read_timeout = read_timeout
        return conn

    @property
    def codec(self) -> FrameCodec:
        """Active frame codec (compression threshold may change during login)."""
        return self._codec

    @property
    def encrypted(self) -> bool:
        """True once AES-CFB8 is active."""
        return self._cipher is not None

    def enable_encryption(self, shared_secret: bytes) -> None:
        """Enable AES-CFB8 for both directions (call at a frame boundary)."""
        self._cipher = CipherPair(shared_secret)

    def set_compression(self, threshold: int) -> None:
        """Update the compression threshold (``-1`` disables)."""
        self._codec.compression_threshold = threshold

    async def read_payload(self) -> bytes:
        """Read one packet payload (id + body), decrypting and inflating as needed."""
        try:
            async with asyncio.timeout(self._read_timeout):
                if self._cipher is None:
                    length = await self._read_varint_plain()
                else:
                    length = await self._read_varint_encrypted()
                if length <= 0:
                    raise FramingError("invalid frame length", length=length)
                if length > self._codec.max_frame:
                    raise FramingError("frame length exceeds limit", length=length)
                raw = await self._reader.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            raise ConnectionClosed(
                "connection closed mid-frame",
                bytes_consumed=len(exc.partial),
            ) from exc
        except TimeoutError as exc:
            # TimeoutError is an OSError subclass, so it must be checked first.
            raise ConnectionClosed("read timed out") from exc
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            raise ConnectionClosed("connection reset while reading", reason=str(exc)) from exc
        if self._cipher is not None:
            raw = self._cipher.decrypt(raw)
        return self._codec.decode(raw)

    async def write_payload(self, payload: bytes) -> None:
        """Frame (and encrypt) one payload and write it."""
        frame = self._codec.encode(payload)
        if self._cipher is not None:
            frame = self._cipher.encrypt(frame)
        async with self._write_lock:
            if self._writer.is_closing():
                raise ConnectionClosed("write after close")
            try:
                self._writer.write(frame)
                await self._writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                raise ConnectionClosed("connection reset while writing", reason=str(exc)) from exc

    async def _read_varint_plain(self) -> int:
        result = 0
        for i in range(5):
            raw = await self._reader.readexactly(1)
            byte = raw[0]
            result |= (byte & 0x7F) << (7 * i)
            if not byte & 0x80:
                value = result & 0xFFFFFFFF
                return value - 0x100000000 if value & 0x80000000 else value
        raise FramingError("frame length VarInt exceeds 5 bytes")

    async def _read_varint_encrypted(self) -> int:
        assert self._cipher is not None
        result = 0
        for i in range(5):
            raw = self._cipher.decrypt(await self._reader.readexactly(1))
            byte = raw[0]
            result |= (byte & 0x7F) << (7 * i)
            if not byte & 0x80:
                value = result & 0xFFFFFFFF
                return value - 0x100000000 if value & 0x80000000 else value
        raise FramingError("frame length VarInt exceeds 5 bytes")

    async def close(self) -> None:
        """Close the connection cleanly (idempotent)."""
        if not self._writer.is_closing():
            self._writer.close()
        with suppress(ConnectionResetError, OSError):
            await self._writer.wait_closed()

    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


# Convenience re-exports for tooling.
__all__ += ["decode_varint", "encode_varint"]
