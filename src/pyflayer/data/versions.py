"""Version parsing and protocol-number mapping.

``minecraft-data`` uses the key ``1.8`` for the 1.8.x family, so user-facing versions are normalized
to a data key. The reference target is Minecraft 1.8.9 (protocol 47).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyflayer.errors import UnsupportedVersion

__all__ = ["VersionInfo", "parse_version", "protocol_for", "version_for_protocol", "version_key"]

_ALIASES = {
    "1.8.9": "1.8",
    "1.8.8": "1.8",
    "1.8.7": "1.8",
    "1.8": "1.8",
}

_KNOWN: dict[str, int] = {
    "1.8": 47,
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

_MAJOR_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """Resolved version information.

    Attributes:
        key: ``minecraft-data`` data key (e.g. ``"1.8"``).
        minecraft_version: Version reported by the data files (e.g. ``"1.8.8"``).
        protocol: Protocol number (47 for 1.8.9).
        major_version: Family key (e.g. ``"1.8"``).
    """

    key: str
    minecraft_version: str
    protocol: int
    major_version: str

    @property
    def release(self) -> tuple[int, int, int]:
        """Parsed semantic release tuple."""
        return parse_version(self.minecraft_version)


def normalize(version: str) -> str:
    """Normalize a user version string (``1.8.9`` -> ``1.8``) when an alias exists."""
    cleaned = version.strip()
    if cleaned.lower().startswith("pc-"):
        cleaned = cleaned[3:]
    return _ALIASES.get(cleaned, cleaned)


def version_key(version: str | int) -> str:
    """Return the data key for a version string or protocol number.

    Raises:
        UnsupportedVersion: When the version is unknown and cannot be parsed.
    """
    if isinstance(version, int):
        for key, protocol in _KNOWN.items():
            if protocol == version:
                return key
        raise UnsupportedVersion(f"unknown protocol number {version}", protocol=version)
    key = normalize(version)
    if key in _KNOWN:
        return key
    if _MAJOR_RE.match(key):
        # Unknown patch/parent: accept the string and let the loader report missing data.
        return key
    raise UnsupportedVersion(f"cannot parse version {version!r}", version=version)


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse ``x.y[.z]`` into a 3-tuple, padding the patch with zero."""
    match = _MAJOR_RE.match(version.strip())
    if not match:
        raise UnsupportedVersion(f"cannot parse version {version!r}", version=version)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def protocol_for(version: str | int) -> int:
    """Protocol number for a version string or number."""
    if isinstance(version, int):
        return version
    key = normalize(version)
    if key not in _KNOWN:
        raise UnsupportedVersion(f"no protocol mapping for {version!r}", version=version)
    return _KNOWN[key]


def version_for_protocol(protocol: int) -> str:
    """Data key for a protocol number."""
    for key, value in _KNOWN.items():
        if value == protocol:
            return key
    raise UnsupportedVersion(f"no version mapping for protocol {protocol}", protocol=protocol)
