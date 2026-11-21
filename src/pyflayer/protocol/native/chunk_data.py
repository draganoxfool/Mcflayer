"""1.8 chunk payload decoding.

A chunk column is split into up to 16 sections. For each section present in the primary bit mask the
wire order is::

    4096 x uint16 little-endian block state   # (block_id << 4) | metadata
    2048 bytes block light                    # nibbles
    2048 bytes sky light                      # when the packet says so

``map_chunk`` follows with 256 biome bytes when it is a ground-up chunk, and may append block
entities. ``map_chunk_bulk`` repeats sections + biomes for every entry in its metadata array and has
no reliable per-chunk block-entity boundary, so trailing bytes are reported instead of guessed.

Examples:
    >>> decode_legacy_chunk(bytes(4096 * 2 + 2048 * 2), 0b1, sky_light=True, include_biomes=True)
    LegacyChunkData(sections={0: ...}, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pyflayer.errors import MalformedPacket
from pyflayer.protocol.buffer import PacketReader
from pyflayer.protocol.types.nbt import read_nbt

__all__ = ["LegacyChunkData", "SECTION_BLOCKS", "decode_legacy_chunk"]

SECTION_BLOCKS = 4096
SECTION_LIGHT_BYTES = 2048
BIOME_BYTES = 256


@dataclass(frozen=True, slots=True)
class LegacyChunkData:
    """Decoded sections of one 1.8 chunk column."""

    sections: dict[int, np.ndarray] = field(default_factory=dict)
    block_light: dict[int, np.ndarray] = field(default_factory=dict)
    sky_light: dict[int, np.ndarray] = field(default_factory=dict)
    biomes: np.ndarray | None = None
    block_entities: tuple[dict[str, object], ...] = ()
    trailing: bytes = b""


def decode_legacy_chunk(
    data: bytes | memoryview,
    bit_map: int,
    *,
    sky_light: bool,
    include_biomes: bool,
    parse_block_entities: bool = True,
) -> LegacyChunkData:
    """Decode one column's byte payload.

    Args:
        data: The ``chunkData`` buffer (or one slice of a bulk payload).
        bit_map: 16-bit mask of present sections.
        sky_light: Whether each section carries 2048 sky-light bytes.
        include_biomes: Whether 256 biome bytes follow the sections.
        parse_block_entities: Parse trailing block entities when their layout is recoverable.

    Raises:
        MalformedPacket: When the payload is shorter than the declared sections/biomes.
    """
    view = memoryview(data)
    offset = 0
    sections: dict[int, np.ndarray] = {}
    block_light: dict[int, np.ndarray] = {}
    sky_lights: dict[int, np.ndarray] = {}

    section_bytes = SECTION_BLOCKS * 2 + SECTION_LIGHT_BYTES + (SECTION_LIGHT_BYTES if sky_light else 0)
    for section_index in range(16):
        if not bit_map & (1 << section_index):
            continue
        if offset + section_bytes > len(view):
            raise MalformedPacket(
                "chunk payload is shorter than its primary bit mask",
                section=section_index,
                offset=offset,
                available=len(view),
            )
        states = np.frombuffer(view[offset : offset + SECTION_BLOCKS * 2], dtype="<u2").copy()
        states.setflags(write=False)
        offset += SECTION_BLOCKS * 2
        light = np.frombuffer(
            view[offset : offset + SECTION_LIGHT_BYTES], dtype=np.uint8
        ).copy()
        light.setflags(write=False)
        offset += SECTION_LIGHT_BYTES
        sections[section_index] = states
        block_light[section_index] = light
        if sky_light:
            sky = np.frombuffer(
                view[offset : offset + SECTION_LIGHT_BYTES], dtype=np.uint8
            ).copy()
            sky.setflags(write=False)
            offset += SECTION_LIGHT_BYTES
            sky_lights[section_index] = sky

    biomes: np.ndarray | None = None
    if include_biomes:
        if offset + BIOME_BYTES > len(view):
            raise MalformedPacket(
                "chunk payload is missing its biome array",
                offset=offset,
                available=len(view),
            )
        biomes = np.frombuffer(view[offset : offset + BIOME_BYTES], dtype=np.uint8).copy()
        biomes.setflags(write=False)
        offset += BIOME_BYTES

    block_entities: tuple[dict[str, object], ...] = ()
    trailing = bytes(view[offset:])
    if parse_block_entities and trailing:
        block_entities, leftover = _parse_block_entities(trailing)
        trailing = leftover

    return LegacyChunkData(
        sections=sections,
        block_light=block_light,
        sky_light=sky_lights,
        biomes=biomes,
        block_entities=block_entities,
        trailing=trailing,
    )


def _parse_block_entities(
    data: bytes,
) -> tuple[tuple[dict[str, object], ...], bytes]:
    """Best-effort parse of ``(short xz, short y, NBT)`` records.

    1.8 does not prefix the record count. Anything that does not parse cleanly is returned as
    leftover bytes so a single odd chunk cannot break the connection.
    """
    reader = PacketReader(data)
    entities: list[dict[str, object]] = []
    while reader.remaining >= 4:
        start = reader.offset
        try:
            xz = reader.read_u16()
            y = reader.read_u16()
            tag = read_nbt(reader, named=True)
        except Exception:  # noqa: BLE001 - block entities are optional metadata
            reader._offset = start  # noqa: SLF001 - restore the cursor for leftover reporting
            break
        value = tag.value if hasattr(tag, "value") else tag
        if not isinstance(value, dict):
            reader._offset = start  # noqa: SLF001
            break
        record = dict(value)
        record["x"] = xz >> 4
        record["z"] = xz & 0x0F
        record["y"] = y
        entities.append(record)
    return tuple(entities), data[reader.offset :]
