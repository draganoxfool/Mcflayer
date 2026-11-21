from __future__ import annotations

import uuid

import pytest

from pyflayer.data import McData
from pyflayer.errors import MalformedPacket
from pyflayer.models.items import ItemStack
from pyflayer.protocol.buffer import PacketReader, PacketWriter
from pyflayer.protocol.native.entity_metadata import EntityMetadataLoopCodec
from pyflayer.protocol.registry import PacketRegistry

MC = McData.load("1.8.9")


def test_metadata_roundtrip_all_types() -> None:
    codec = EntityMetadataLoopCodec()
    metadata = {
        0: (0, 1),  # byte
        1: (1, -2),  # short
        2: (2, 300),  # int
        3: (3, 1.5),  # float
        4: (4, "hello"),  # string
        5: (5, ItemStack(item_id=1, count=1)),
        6: (6, (1, 2, 3)),  # vector int
        7: (7, (1.0, 2.0, 3.0)),
    }
    writer = PacketWriter()
    codec.write(writer, metadata, {})
    decoded = codec.read(PacketReader(writer.to_bytes()), {})
    assert decoded[0] == 1
    assert decoded[1] == -2
    assert decoded[2] == 300
    assert decoded[4] == "hello"
    assert decoded[5].item_id == 1
    assert decoded[6] == (1, 2, 3)
    assert decoded[7] == (1.0, 2.0, 3.0)


def test_metadata_requires_terminator() -> None:
    codec = EntityMetadataLoopCodec()
    with pytest.raises(MalformedPacket):
        codec.read(PacketReader(b"\x20\x01"), {})


def test_registry_decodes_named_entity_spawn() -> None:
    registry = PacketRegistry(MC)
    player_uuid = uuid.uuid4()
    payload = registry.encode(
        "play",
        "toClient",
        "named_entity_spawn",
        {
            "entityId": 9,
            "playerUUID": player_uuid,
            "x": 32,
            "y": 2048,
            "z": -32,
            "yaw": 64,
            "pitch": 0,
            "currentItem": 0,
            "metadata": {0: (0, 1), 2: "name"},
        },
    )
    packet = registry.decode("play", "toClient", payload)
    assert packet.fields["playerUUID"] == player_uuid
    assert packet.fields["metadata"] == {0: 1, 2: "name"}


def test_registry_decodes_entity_metadata_packet() -> None:
    registry = PacketRegistry(MC)
    payload = registry.encode(
        "play", "toClient", "entity_metadata", {"entityId": 3, "metadata": {4: "hi"}}
    )
    packet = registry.decode("play", "toClient", payload)
    assert packet.fields["entityId"] == 3
    assert packet.fields["metadata"] == {4: "hi"}


def test_all_play_packets_compile() -> None:
    registry = PacketRegistry(MC)
    for direction in ("toClient", "toServer"):
        report = registry.compiler.compile_state("play", direction)
        assert report.ok, report.unsupported
