"""Bytes <-> packets: framing, crypto, protodef codecs, login client and server list ping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.client import ProtocolClient
from pyflayer.protocol.connection import Connection, resolve_address
from pyflayer.protocol.crypto import CipherPair
from pyflayer.protocol.framing import FrameCodec
from pyflayer.protocol.protodef import Packet, PacketCodec, ProtocolCompiler
from pyflayer.protocol.registry import PacketRegistry
from pyflayer.protocol.state import ConnectionState, StateMachine
from pyflayer.protocol.varint import decode_varint, decode_varlong, encode_varint, encode_varlong

__all__ = [
    "CipherPair",
    "Connection",
    "ConnectionState",
    "FrameCodec",
    "Packet",
    "PacketCodec",
    "PacketReader",
    "PacketRegistry",
    "PacketWriter",
    "ProtocolClient",
    "ProtocolCompiler",
    "ServerStatus",
    "StateMachine",
    "decode_varint",
    "decode_varlong",
    "encode_varint",
    "encode_varlong",
    "ping",
    "resolve_address",
]

if TYPE_CHECKING:
    from pyflayer.protocol.status import ServerStatus, ping


def __getattr__(name: str) -> object:
    # Import SLP lazily so `python -m pyflayer.protocol.status` does not pre-import the module.
    if name in {"ServerStatus", "ping"}:
        from pyflayer.protocol import status

        return getattr(status, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
