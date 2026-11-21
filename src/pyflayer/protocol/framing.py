"""Frame framing, compression and size limits.

Wire layout::

    [frame length: VarInt][frame body]

With compression enabled (threshold >= 0), the body is::

    [uncompressed length: VarInt][zlib data]   # if uncompressed length > 0
    [0][raw packet]                            # if uncompressed length == 0

The threshold is negotiated during login (``set_compression``); ``-1`` disables compression. A
declared uncompressed length larger than :data:`MAX_UNCOMPRESSED` is rejected *before* inflating to
guard against zlib bombs.
"""

from __future__ import annotations

import zlib

from pyflayer.errors import CompressionError, FramingError
from pyflayer.protocol.buffer import PacketReader
from pyflayer.protocol.varint import decode_varint, encode_varint

__all__ = [
    "MAX_FRAME",
    "MAX_UNCOMPRESSED",
    "FrameCodec",
    "read_frame_async",
    "write_frame_async",
]

MAX_FRAME = 2**21 - 1
MAX_UNCOMPRESSED = 2**23


class FrameCodec:
    """Encode/decode one frame body, with optional compression."""

    __slots__ = ("compression_threshold", "max_frame", "max_uncompressed")

    def __init__(
        self,
        compression_threshold: int = -1,
        *,
        max_frame: int = MAX_FRAME,
        max_uncompressed: int = MAX_UNCOMPRESSED,
    ) -> None:
        self.compression_threshold = compression_threshold
        self.max_frame = max_frame
        self.max_uncompressed = max_uncompressed

    @property
    def compression_enabled(self) -> bool:
        """True when the body may be compressed."""
        return self.compression_threshold >= 0

    def encode(self, payload: bytes) -> bytes:
        """Wrap a packet payload (id + fields) in a length-prefixed frame."""
        if self.compression_enabled:
            if len(payload) >= self.compression_threshold:
                compressed = zlib.compress(payload)
                body = encode_varint(len(payload)) + compressed
            else:
                body = encode_varint(0) + payload
        else:
            body = payload
        if len(body) > self.max_frame:
            raise FramingError("frame too large", size=len(body), limit=self.max_frame)
        return encode_varint(len(body)) + body

    def decode(self, body: bytes | memoryview) -> bytes:
        """Unwrap a frame body (without the outer length prefix) to a packet payload."""
        view = memoryview(body)
        if len(view) > self.max_frame:
            raise FramingError("frame too large", size=len(view), limit=self.max_frame)
        if not self.compression_enabled:
            return view.tobytes()
        if not view:
            raise CompressionError("compressed frame has no data-length prefix")
        declared, prefix = decode_varint(view)
        if declared < 0:
            raise CompressionError("negative uncompressed length", declared=declared)
        data = view[prefix:]
        if declared == 0:
            if len(data) >= self.compression_threshold:
                raise CompressionError(
                    "uncompressed packet at or above threshold",
                    size=len(data),
                    threshold=self.compression_threshold,
                )
            return data.tobytes()
        if declared > self.max_uncompressed:
            raise CompressionError(
                "declared uncompressed size exceeds limit",
                declared=declared,
                limit=self.max_uncompressed,
            )
        if declared < self.compression_threshold:
            raise CompressionError(
                "compressed packet below threshold",
                declared=declared,
                threshold=self.compression_threshold,
            )
        decompressor = zlib.decompressobj()
        try:
            out = decompressor.decompress(data, declared + 1)
        except zlib.error as exc:
            raise CompressionError("zlib inflate failed", reason=str(exc)) from exc
        if decompressor.unconsumed_tail:
            raise CompressionError(
                "decompressed data larger than declared", declared=declared, actual=len(out)
            )
        if len(out) > declared:
            raise CompressionError(
                "decompressed data larger than declared", declared=declared, actual=len(out)
            )
        out += decompressor.flush()
        if len(out) != declared:
            raise CompressionError(
                "decompressed length mismatch", declared=declared, actual=len(out)
            )
        if decompressor.unused_data:
            raise CompressionError(
                "trailing data after zlib stream", trailing=len(decompressor.unused_data)
            )
        if not decompressor.eof:
            raise CompressionError("truncated zlib stream")
        return out


async def read_frame_async(reader: object, codec: FrameCodec) -> bytes:
    """Read one complete frame from an asyncio stream-like reader."""
    from pyflayer.protocol.varint import read_varint

    try:
        length = await read_varint(reader)
    except Exception:
        raise
    if length <= 0:
        raise FramingError("invalid frame length", length=length)
    if length > codec.max_frame:
        raise FramingError("frame length exceeds limit", length=length, limit=codec.max_frame)
    try:
        body = await reader.readexactly(length)  # type: ignore[attr-defined]
    except Exception as exc:
        if exc.__class__.__name__ == "IncompleteReadError":
            raise FramingError("connection closed mid-frame", expected=length) from exc
        raise
    return codec.decode(body)


async def write_frame_async(writer: object, payload: bytes, codec: FrameCodec) -> None:
    """Write one framed payload to an asyncio stream writer."""
    writer.write(codec.encode(payload))  # type: ignore[attr-defined]
    await writer.drain()  # type: ignore[attr-defined]


def decode_packet_id(payload: bytes) -> tuple[int, bytes]:
    """Split a payload into ``(packet_id, body)``."""
    packet_id, consumed = decode_varint(payload)
    return packet_id, payload[consumed:]


def peek_packet_size(payload: bytes) -> int:
    """Return the length of the packet-id prefix (for debugging)."""
    _value, consumed = decode_varint(payload)
    return consumed


def frame_reader(body: bytes) -> PacketReader:
    """Convenience: a reader over a frame body."""
    return PacketReader(body)
