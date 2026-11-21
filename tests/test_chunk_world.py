from __future__ import annotations

import numpy as np
import pytest

from pyflayer.data import McData
from pyflayer.errors import ChunkNotLoaded, OutOfWorldBounds
from pyflayer.models.vec3 import BlockPos, ChunkPos, Vec3
from pyflayer.protocol.native.chunk_data import decode_legacy_chunk
from pyflayer.world import (
    Bounds,
    ChunkColumn,
    ChunkSection,
    ChunkStore,
    World,
    WorldKey,
    section_index,
)

MC = McData.load("1.8.9")
STONE = 16  # (1 << 4) | 0
DIRT = 48  # (3 << 4) | 0
FLOWING_WATER = 8 << 4


def section_bytes(states: np.ndarray, *, sky: bool = True) -> bytes:
    return states.astype("<u2").tobytes() + bytes(2048) + (bytes(2048) if sky else b"")


def one_section_chunk(
    section_y: int = 4, state: int = STONE, *, sky: bool = True
) -> tuple[bytes, int]:
    # Only the bottom layer of the section is solid, so block (0, 64, 0) is stone and the block
    # above it is air (a useful raycast/placement fixture).
    states = np.zeros(4096, dtype=np.uint16)
    states[:256] = state
    return section_bytes(states, sky=sky) + bytes([1]) * 256, 1 << section_y


def build_column(pos: ChunkPos | None = None, *, state: int = STONE) -> ChunkColumn:
    if pos is None:
        pos = ChunkPos(0, 0)
    data, bit_map = one_section_chunk(state=state)
    decoded = decode_legacy_chunk(data, bit_map, sky_light=True, include_biomes=True)
    return ChunkColumn.from_legacy(pos, decoded)


def test_decode_sections_and_biomes() -> None:
    data, bit_map = one_section_chunk()
    decoded = decode_legacy_chunk(data, bit_map, sky_light=True, include_biomes=True)
    assert set(decoded.sections) == {4}
    assert decoded.sections[4][0] == STONE
    assert decoded.biomes is not None and decoded.biomes[0] == 1
    assert not decoded.sections[4].flags.writeable


def test_decode_short_payload_raises() -> None:
    from pyflayer.errors import MalformedPacket

    with pytest.raises(MalformedPacket):
        decode_legacy_chunk(b"\x00" * 10, 1 << 4, sky_light=True, include_biomes=True)


def test_section_index_order_and_cow() -> None:
    section = ChunkSection.from_legacy(np.zeros(4096, dtype=np.uint16))
    assert section_index(1, 2, 3) == (2 << 8) | (3 << 4) | 1
    changed = section.with_state(1, 2, 3, STONE)
    assert changed.state_at(1, 2, 3) == STONE
    assert section.state_at(1, 2, 3) == 0
    assert changed.non_air == 1
    assert changed.with_state(1, 2, 3, STONE) is changed


def test_column_block_reads_and_copy() -> None:
    column = build_column()
    assert column.block_state_id(0, 64, 0) == STONE
    assert column.block_state_id(0, 0, 0) == 0  # absent section is air
    clone = column.copy()
    assert clone.block_state_id(0, 64, 0) == STONE
    assert column.non_air == 256
    assert column.section_count == 1


def test_partial_chunk_update_keeps_untouched_sections() -> None:
    column = build_column()
    states = np.zeros(4096, dtype=np.uint16)
    states[:256] = DIRT
    decoded = decode_legacy_chunk(
        section_bytes(states), 1 << 5, sky_light=True, include_biomes=False
    )
    updated = column.with_legacy_update(decoded)
    assert updated is not column
    assert updated.version == column.version + 1
    assert updated.block_state_id(0, 64, 0) == STONE  # section 4 was not in the update
    assert updated.block_state_id(0, 80, 0) == DIRT
    assert updated.non_air == 512
    assert column.block_state_id(0, 80, 0) == 0


def test_world_set_get_snapshot_and_events_data() -> None:
    world = World(MC)
    assert not world.is_loaded(ChunkPos(0, 0))
    with pytest.raises(ChunkNotLoaded):
        world.block_state_id(BlockPos(0, 64, 0))
    assert world.block_state_id_or(BlockPos(0, 64, 0), -1) == -1
    world.apply_chunk(build_column())
    assert world.is_loaded(ChunkPos(0, 0))
    assert world.block_at(BlockPos(0, 64, 0)).name == "stone"
    with pytest.raises(OutOfWorldBounds):
        world.block_state_id(BlockPos(0, 300, 0))

    snapshot = world.snapshot()
    assert snapshot.block_state_id(BlockPos(0, 64, 0)) == STONE
    assert world.set_block_state(BlockPos(0, 64, 0), DIRT)
    assert not world.set_block_state(BlockPos(0, 64, 0), DIRT)  # no-op
    assert snapshot.block_state_id(BlockPos(0, 64, 0)) == STONE
    assert world.block_at(BlockPos(0, 64, 0)).block_id == 3
    assert snapshot.block_at(BlockPos(0, 64, 0)).block_id == 1
    assert snapshot.collision_boxes(BlockPos(0, 64, 0))
    assert snapshot.collision_boxes(BlockPos(0, 300, 0)) == ()


def test_snapshot_bounds() -> None:
    world = World(MC)
    world.apply_chunk(build_column(ChunkPos(0, 0)))
    world.apply_chunk(build_column(ChunkPos(10, 10)))
    snapshot = world.snapshot(Bounds(0, 0, 0, 15, 255, 15))
    assert len(snapshot) == 1
    assert snapshot.is_loaded(ChunkPos(0, 0))
    assert not snapshot.is_loaded(ChunkPos(10, 10))


def test_multi_block_change_and_unload() -> None:
    world = World(MC)
    world.apply_chunk(build_column())
    applied = world.apply_multi_block_change(ChunkPos(0, 0), [(1, 64, 2, DIRT), (0, 0, 0, STONE)])
    assert len(applied) == 2
    assert world.block_state_id(BlockPos(1, 64, 2)) == DIRT
    assert world.block_state_id(BlockPos(0, 0, 0)) == STONE
    column = world.unload_chunk(ChunkPos(0, 0))
    assert column is not None and not world.is_loaded(ChunkPos(0, 0))


def test_find_blocks_nearest_first() -> None:
    world = World(MC)
    states = np.zeros(4096, dtype=np.uint16)
    states[section_index(1, 0, 1)] = STONE
    states[section_index(10, 0, 10)] = STONE
    data = section_bytes(states) + bytes(256)
    decoded = decode_legacy_chunk(data, 1 << 4, sky_light=True, include_biomes=True)
    world.apply_chunk(ChunkColumn.from_legacy(ChunkPos(0, 0), decoded))

    found = world.find_blocks("stone", within=32, around=Vec3(0.5, 64.5, 0.5), count=2)
    assert found == [BlockPos(1, 64, 1), BlockPos(10, 64, 10)]
    assert world.find_blocks("stone", within=2, around=Vec3(0.5, 64.5, 0.5)) == [BlockPos(1, 64, 1)]
    assert world.find_blocks("not_a_block") == []
    assert world.find_blocks(
        lambda state: state == STONE, within=8, around=Vec3(0.5, 64.5, 0.5), count=1
    ) == [BlockPos(1, 64, 1)]


def test_raycast_hits_top_face() -> None:
    world = World(MC)
    world.apply_chunk(build_column())
    hit = world.raycast(Vec3(0.5, 70.5, 0.5), Vec3(0, -1, 0), 10)
    assert hit is not None
    assert hit.pos == BlockPos(0, 64, 0)
    assert hit.face is not None and hit.face.name == "UP"
    assert world.raycast(Vec3(0.5, 70.5, 0.5), Vec3(0, 1, 0), 3) is None


def test_raycast_include_fluids_covers_flowing_water() -> None:
    world = World(MC)
    world.apply_chunk(build_column(state=FLOWING_WATER))

    origin = Vec3(0.5, 70.5, 0.5)
    assert world.raycast(origin, Vec3(0, -1, 0), 10) is None
    hit = world.raycast(origin, Vec3(0, -1, 0), 10, include_fluids=True)
    assert hit is not None
    assert hit.pos == BlockPos(0, 64, 0)
    assert hit.face is not None and hit.face.name == "UP"


def test_chunk_store_refcounts() -> None:
    store = ChunkStore(WorldKey("example.org", 0))
    column = build_column()
    assert store.put(column, from_bot=1)
    assert not store.put(column, from_bot=2)  # duplicate adds a ref only
    assert store.refcount == 2
    assert store.get(ChunkPos(0, 0)) is column
    assert not store.release(1, ChunkPos(0, 0))
    assert store.release(2, ChunkPos(0, 0))
    assert len(store) == 0
    assert store.refcount == 0
    assert not store.apply_block(BlockPos(0, 64, 0), DIRT)
