"""Hand-written codecs for types protodef can express only with game semantics.

1.8's ``entityMetadataLoop`` is declared as ``"native"`` in ``protocol.json`` and chunk payloads are
opaque buffers; both are decoded here and injected into the protodef compiler.
"""

from __future__ import annotations

from pyflayer.protocol.native.chunk_data import LegacyChunkData, decode_legacy_chunk
from pyflayer.protocol.native.entity_metadata import EntityMetadataLoopCodec

__all__ = ["EntityMetadataLoopCodec", "LegacyChunkData", "decode_legacy_chunk"]
