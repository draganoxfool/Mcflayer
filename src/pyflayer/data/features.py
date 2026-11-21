"""Feature flags for version-gated protocol and data differences (ADR-7).

Feature flags are evaluated from known version facts plus optional ``features.json`` data. Protocol
code must not scatter ``if version >= ...`` checks; it asks a :class:`Features` instance instead.

Examples:
    >>> Features.for_version("1.8.9").position_packed_xzy
    False
    >>> Features.for_version("1.20.4").position_packed_xzy
    True
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from pyflayer.data.versions import version_key

__all__ = ["Features"]


@dataclass(frozen=True, slots=True)
class Features:
    """Boolean capabilities for one Minecraft version."""

    version: str = "1.8.9"
    protocol: int = 47
    #: Position is ``x<<38 | z<<12 | y`` (1.14+). Older is ``x<<38 | y<<26 | z`` (1.8-1.13).
    position_packed_xzy: bool = False
    #: Network NBT has no root name (1.20.2+, protocol 764+).
    network_nbt_nameless: bool = False
    #: Slots encode the item id as a VarInt (1.13+); older uses i16 and a damage value.
    slot_item_id_varint: bool = False
    #: Item stacks use structured components (1.20.5+, protocol 766+).
    item_components: bool = False
    #: Blocks have global block-state ids (1.13+); older uses block id + metadata.
    block_state_ids: bool = False
    #: The configuration state exists (1.20.2+).
    configuration_state: bool = False
    #: Chunk batch start/finished packets exist (1.20.2+).
    chunk_batches: bool = False
    #: Paletted containers use the non-spanning packing (1.16+).
    palette_non_spanning: bool = True
    #: The login start packet includes the player UUID (1.20.2+).
    login_start_uuid: bool = False
    #: Built-in compression was introduced in 1.8 (protocol 47).
    compression_supported: bool = True
    #: Server teleports carry an id and the client answers with ``teleport_confirm`` (1.9+).
    teleport_confirm: bool = False

    @classmethod
    def for_version(cls, version: str | int) -> Features:
        """Build feature flags for a version string or protocol number."""
        key = version_key(version)
        protocol = _protocol_for(key)
        major = _major_tuple(key)
        return cls(
            version=key,
            protocol=protocol,
            position_packed_xzy=major >= (1, 14),
            network_nbt_nameless=protocol >= 764,
            slot_item_id_varint=major >= (1, 13),
            item_components=protocol >= 766,
            block_state_ids=major >= (1, 13),
            configuration_state=protocol >= 764,
            chunk_batches=protocol >= 764,
            palette_non_spanning=major >= (1, 16),
            login_start_uuid=protocol >= 764,
            compression_supported=protocol >= 47,
            teleport_confirm=protocol >= 107,
        )

    def supports(self, name: str) -> bool:
        """Return a feature by attribute name; unknown names are ``False``."""
        if name in {f.name for f in fields(self)}:
            return bool(getattr(self, name))
        return False

    def as_dict(self) -> dict[str, bool]:
        """Return only the boolean capabilities (useful for logging/tests)."""
        return {
            f.name: bool(getattr(self, f.name))
            for f in fields(self)
            if f.name not in {"version", "protocol"}
        }


_PROTOCOLS: dict[str, int] = {
    "1.8": 47,
    "1.8.9": 47,
    "1.9": 107,
    "1.9.4": 110,
    "1.10.2": 210,
    "1.11.2": 316,
    "1.12.2": 340,
    "1.13.2": 404,
    "1.14.4": 498,
    "1.15.2": 578,
    "1.16.5": 754,
    "1.17.1": 756,
    "1.18.2": 758,
    "1.19.4": 762,
    "1.20.1": 763,
    "1.20.4": 765,
    "1.20.6": 766,
    "1.21.1": 767,
    "1.21.4": 769,
    "1.21.5": 770,
    "1.21.6": 771,
}


def _protocol_for(key: str) -> int:
    if key in _PROTOCOLS:
        return _PROTOCOLS[key]
    return 0


def _major_tuple(key: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in key.split("-")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)
