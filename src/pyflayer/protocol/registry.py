"""Packet registry: ``(state, direction) -> id <-> name <-> codec``.

The registry compiles lazily and caches one :class:`~pyflayer.protocol.protodef.PacketCodec` per
state/direction. Unknown ids raise :class:`~pyflayer.errors.UnknownPacket` carrying the raw body; the
decision to treat that as fatal belongs to the connection state machine (M2), not here.
"""

from __future__ import annotations

from pyflayer.data.loader import McData
from pyflayer.errors import MissingRegistryEntry, UnsupportedType
from pyflayer.protocol.protodef import Codec, Packet, PacketCodec, ProtocolCompiler

__all__ = ["PacketRegistry"]


class PacketRegistry:
    """Registry of packet codecs for one data snapshot."""

    __slots__ = ("mc", "compiler", "_codecs", "_native")

    def __init__(
        self,
        mc: McData,
        *,
        native_packets: dict[tuple[str, str, str], Codec] | None = None,
    ) -> None:
        self.mc = mc
        self._native = dict(native_packets or {})
        self.compiler = ProtocolCompiler(mc.protocol, mc.features, native_packets=self._native)
        self._codecs: dict[tuple[str, str], PacketCodec] = {}

    def codec(self, state: str, direction: str) -> PacketCodec:
        """Return (and lazily build) the codec for a state/direction."""
        key = (state, direction)
        codec = self._codecs.get(key)
        if codec is None:
            codec = PacketCodec.build(self.mc, self.compiler, state, direction)
            if not codec.ids:
                raise MissingRegistryEntry(
                    f"no packet ids for {state}/{direction}",
                    registry="protocol",
                    key=key,
                )
            self._codecs[key] = codec
        return codec

    def decode(self, state: str, direction: str, payload: bytes, *, strict: bool = True) -> Packet:
        """Decode a payload in a given state/direction."""
        return self.codec(state, direction).decode(payload, strict=strict)

    def encode(self, state: str, direction: str, name: str, fields: dict[str, object]) -> bytes:
        """Encode a packet in a given state/direction."""
        return self.codec(state, direction).encode(name, fields)

    def packet_names(self, state: str, direction: str) -> tuple[str, ...]:
        """All known packet names."""
        return tuple(self.codec(state, direction).names)

    def packet_id(self, state: str, direction: str, name: str) -> int:
        """Packet id for a name."""
        return self.codec(state, direction).names[name]

    def packet_name(self, state: str, direction: str, packet_id: int) -> str:
        """Packet name for an id."""
        return self.codec(state, direction).ids[packet_id]

    def compile_all(self, state: str, direction: str) -> dict[str, str]:
        """Compile every packet; return ``name -> error`` for unsupported ones."""
        report = self.compiler.compile_state(state, direction)
        return report.unsupported

    def register_native(self, state: str, direction: str, name: str, codec: Codec) -> None:
        """Install an override codec for one packet (used by ``protocol/native``)."""
        self._native[(state, direction, name)] = codec
        self.compiler.native_packets[(state, direction, name)] = codec
        self._codecs.pop((state, direction), None)

    def __repr__(self) -> str:
        return f"PacketRegistry(version={self.mc.version.minecraft_version!r})"


# Re-export for callers that only import registry.
__all__ += ["UnsupportedType"]
