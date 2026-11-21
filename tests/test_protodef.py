from __future__ import annotations

import pytest

from pyflayer.data import McData
from pyflayer.errors import MalformedPacket, UnknownPacket, UnsupportedType
from pyflayer.protocol.buffer import PacketWriter
from pyflayer.protocol.registry import PacketRegistry
from pyflayer.protocol.varint import decode_varint, encode_varint


@pytest.fixture(scope="module")
def registry() -> PacketRegistry:
    return PacketRegistry(McData.load("1.8.9"))


def test_handshake_golden_bytes(registry: PacketRegistry) -> None:
    payload = registry.encode(
        "handshaking",
        "toServer",
        "set_protocol",
        {
            "protocolVersion": 47,
            "serverHost": "localhost",
            "serverPort": 25565,
            "nextState": 1,
        },
    )
    assert payload == b"\x00\x2f\x09localhost\x63\xdd\x01"
    decoded = registry.decode("handshaking", "toServer", payload)
    assert decoded.name == "set_protocol"
    assert decoded.fields["protocolVersion"] == 47
    assert decoded.fields["serverHost"] == "localhost"
    assert decoded.fields["nextState"] == 1


def test_status_packets(registry: PacketRegistry) -> None:
    request = registry.encode("status", "toServer", "ping_start", {})
    assert request == b"\x00"
    ping_payload = registry.encode("status", "toServer", "ping", {"time": 123})
    assert registry.decode("status", "toServer", ping_payload).fields == {"time": 123}

    response = registry.encode(
        "status",
        "toClient",
        "server_info",
        {"response": '{"version":{"name":"1.8.9","protocol":47}}'},
    )
    decoded = registry.decode("status", "toClient", response)
    assert decoded.fields["response"].startswith("{")


def test_login_packets(registry: PacketRegistry) -> None:
    login = registry.encode("login", "toServer", "login_start", {"username": "Bot"})
    assert registry.decode("login", "toServer", login).fields == {"username": "Bot"}
    assert registry.compiler.compile_state("login", "toClient").ok
    assert registry.compiler.compile_state("login", "toServer").ok
    assert registry.compiler.compile_state("status", "toClient").ok
    assert registry.compiler.compile_state("status", "toServer").ok
    assert registry.compiler.compile_state("handshaking", "toServer").ok


def test_play_packet_roundtrip(registry: PacketRegistry) -> None:
    payload = registry.encode(
        "play",
        "toServer",
        "position",
        {"x": 1.5, "y": 64.0, "z": -3.5, "onGround": True},
    )
    decoded = registry.decode("play", "toServer", payload)
    assert decoded.name == "position"
    assert decoded.fields["x"] == pytest.approx(1.5)
    assert decoded.fields["onGround"] is True


def test_play_to_client_chat(registry: PacketRegistry) -> None:
    payload = registry.encode(
        "play", "toClient", "chat", {"message": '{"text":"hi"}', "position": 0}
    )
    assert registry.decode("play", "toClient", payload).fields["message"] == '{"text":"hi"}'


def test_every_play_to_client_packet_compiles(registry: PacketRegistry) -> None:
    report = registry.compiler.compile_state("play", "toClient")
    assert report.ok
    assert report.unsupported == {}
    assert "entity_metadata" in report.compiled
    assert "named_entity_spawn" in report.compiled
    assert "spawn_entity_living" in report.compiled


def test_unknown_packet_id_carries_raw(registry: PacketRegistry) -> None:
    payload = encode_varint(0x7E) + b"\x01\x02\x03"
    with pytest.raises(UnknownPacket) as info:
        registry.decode("play", "toServer", payload)
    assert info.value.packet_id == 0x7E
    assert info.value.raw == b"\x01\x02\x03"


def test_unknown_packet_name(registry: PacketRegistry) -> None:
    with pytest.raises(UnsupportedType):
        registry.encode("play", "toServer", "not_a_packet", {})


def test_strict_trailing_bytes(registry: PacketRegistry) -> None:
    payload = registry.encode("status", "toServer", "ping_start", {}) + b"\xff"
    with pytest.raises(MalformedPacket):
        registry.decode("status", "toServer", payload)
    assert registry.decode("status", "toServer", payload, strict=False).name == "ping_start"


def test_packet_ids_and_names(registry: PacketRegistry) -> None:
    assert registry.packet_id("handshaking", "toServer", "set_protocol") == 0x00
    assert registry.packet_name("status", "toServer", 0x01) == "ping"
    assert "login_start" in registry.packet_names("login", "toServer")
    assert decode_varint(b"\x00") == (0, 1)


def test_all_play_directions_compile() -> None:
    mc = McData.load("1.8.9")
    compiler = PacketRegistry(mc).compiler
    for direction in ("toClient", "toServer"):
        report = compiler.compile_state("play", direction)
        assert report.ok, report.unsupported


def test_writer_string_with_surrogate_pair() -> None:
    writer = PacketWriter()
    writer.write_string("a𝄞b")
    # The prefix is the UTF-8 byte length (6), not the character or UTF-16 count.
    assert writer.to_bytes() == b"\x06a\xf0\x9d\x84\x9eb"


def test_option_with_bare_type_reads_inner_value() -> None:
    """``["option", "string"]`` must decode the string, not ``option(void)``.

    Regression: treating the bare type name as an empty params mapping compiled ``option(void)``,
    so every optional field consumed only its presence flag and shifted the rest of the packet.
    """
    from pyflayer.protocol.buffer import PacketReader
    from pyflayer.protocol.protodef import PacketCodec, ProtocolCompiler

    mc = McData.load("1.8.9")
    compiler = ProtocolCompiler(mc.protocol, mc.features)
    codec = compiler.compile_type(["option", "string"], "play", "toClient")

    writer = PacketWriter()
    codec.write(writer, "hello", {})
    assert writer.to_bytes() == b"\x01\x05hello"
    reader = PacketReader(writer.to_bytes())
    assert codec.read(reader, {}) == "hello"

    empty = PacketWriter()
    codec.write(empty, None, {})
    assert empty.to_bytes() == b"\x00"
    assert codec.read(PacketReader(empty.to_bytes()), {}) is None

    # Unused import keeps the public symbol importable for callers/tests.
    assert PacketCodec is not None


def test_player_info_property_signature_is_consumed(registry: PacketRegistry) -> None:
    """A present property signature must not be read as the next property's name."""
    uuid = bytes.fromhex("09a0144923a33eac9c413364ca6549a1")
    writer = PacketWriter()
    writer.write_varint(0)  # action: add_player
    writer.write_varint(1)  # one entry
    writer.write_uuid(type("U", (), {"bytes": uuid})())
    writer.write_string("Aimify")
    writer.write_varint(1)  # one property
    writer.write_string("textures")
    writer.write_string("value")
    writer.write_bool(True)
    writer.write_string("signature")
    writer.write_varint(0)  # gamemode
    writer.write_varint(42)  # ping
    writer.write_bool(False)  # no display name

    payload = encode_varint(registry.packet_id("play", "toClient", "player_info")) + writer.to_bytes()
    packet = registry.decode("play", "toClient", payload)
    entry = packet.fields["data"][0]
    assert entry["gamemode"] == 0
    assert entry["ping"] == 42
    assert entry["properties"][0]["signature"] == "signature"
