"""Load ``minecraft-data`` into an immutable :class:`McData` snapshot.

Resolution order for the data directory:

1. ``PYFLAYER_DATA_DIR`` environment variable (a full ``minecraft-data/data`` checkout);
2. ``<repo>/data`` next to ``src/`` (the vendored 1.8 subset);
3. ``./data``.

``dataPaths.json`` maps ``pc -> version -> {file: directory}``. Some upstream formats nest an extra
edition dictionary; both are handled. Results are cached per ``(version key, data dir)``.

Examples:
    >>> mc = McData.load("1.8.9")
    >>> mc.version.protocol
    47
    >>> mc.blocks["stone"].id
    1
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import msgspec

from pyflayer.data.features import Features
from pyflayer.data.registries import (
    BiomeRegistry,
    BlockRegistry,
    EffectRegistry,
    EntityRegistry,
    FoodRegistry,
    ItemRegistry,
)
from pyflayer.data.schema import (
    BiomeJson,
    BlockJson,
    CollisionShapesJson,
    EffectJson,
    EntityJson,
    FoodJson,
    ItemJson,
    VersionJson,
)
from pyflayer.data.shapes import ShapeTable
from pyflayer.data.versions import VersionInfo, normalize, version_key
from pyflayer.errors import DataError, UnsupportedVersion

__all__ = ["McData", "ProtocolSchema", "default_data_dir"]


def default_data_dir() -> Path:
    """Return the first existing data directory, preferring ``PYFLAYER_DATA_DIR``."""
    env = os.environ.get("PYFLAYER_DATA_DIR")
    if env:
        path = Path(env).expanduser()
        if not path.exists():
            raise DataError("PYFLAYER_DATA_DIR does not exist", path=str(path))
        return path
    packaged = Path(__file__).resolve().parents[1] / "_data"
    if packaged.exists():
        return packaged
    repo = Path(__file__).resolve().parents[3] / "data"
    if repo.exists():
        return repo
    cwd = Path.cwd() / "data"
    if cwd.exists():
        return cwd
    raise DataError(
        "cannot find minecraft-data; set PYFLAYER_DATA_DIR to a minecraft-data/data checkout"
    )


@dataclass(frozen=True, slots=True)
class ProtocolSchema:
    """Raw protodef schema plus convenient indexes.

    Attributes:
        raw: The full ``protocol.json`` mapping.
        global_types: Top-level reusable types (``varint``, ``string``, ...).
        states: ``state -> direction -> {type_name: type_spec}``.
    """

    raw: dict[str, Any]
    global_types: dict[str, Any]
    states: dict[str, dict[str, dict[str, Any]]]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ProtocolSchema:
        """Index a decoded ``protocol.json``."""
        global_types = dict(raw.get("types", {})) if isinstance(raw.get("types"), dict) else {}
        states: dict[str, dict[str, dict[str, Any]]] = {}
        for state_name, state_value in raw.items():
            if state_name == "types" or not isinstance(state_value, dict):
                continue
            directions: dict[str, dict[str, Any]] = {}
            for direction, direction_value in state_value.items():
                if isinstance(direction_value, dict):
                    types = direction_value.get("types", {})
                    if isinstance(types, dict):
                        directions[direction] = dict(types)
            states[state_name] = directions
        return cls(raw, global_types, states)

    def types(self, state: str, direction: str) -> dict[str, Any]:
        """Type table for one state/direction (empty if unknown)."""
        return self.states.get(state, {}).get(direction, {})

    def packet_type(self, state: str, direction: str) -> Any | None:
        """The top-level ``packet`` type spec, if the state defines one."""
        return self.types(state, direction).get("packet")

    def directions(self, state: str) -> tuple[str, ...]:
        """Directions defined for a state."""
        return tuple(self.states.get(state, {}))


@dataclass(frozen=True, slots=True)
class McData:
    """Immutable, versioned data snapshot consumed by the rest of the library."""

    version: VersionInfo
    features: Features
    blocks: BlockRegistry
    items: ItemRegistry
    entities: EntityRegistry
    biomes: BiomeRegistry
    effects: EffectRegistry
    foods: FoodRegistry
    shapes: ShapeTable
    protocol: ProtocolSchema

    @classmethod
    def load(cls, version: str | int, *, edition: str = "pc") -> McData:
        """Load and cache data for a version.

        Args:
            version: Version string (``"1.8.9"``) or protocol number (``47``).
            edition: Only ``"pc"`` (Java Edition) is supported.

        Raises:
            UnsupportedVersion: The version has no data.
            DataError: Data files are missing or malformed.
        """
        if edition != "pc":
            raise UnsupportedVersion("only the PC (Java) edition is supported", edition=edition)
        key = version_key(version)
        return _load_cached(key, str(default_data_dir()))

    def supports(self, feature: str) -> bool:
        """Shortcut for ``self.features.supports(feature)``."""
        return self.features.supports(feature)

    def collision_boxes(self, state_id: int):
        """Legacy collision boxes for a block state id (1.8); M3 adds modern state ids."""
        return self.shapes.boxes_for_legacy_state(state_id, self.blocks)


@lru_cache(maxsize=8)
def _load_cached(key: str, data_dir: str) -> McData:
    return _load(Path(data_dir), key)


def _load(data_dir: Path, key: str) -> McData:
    paths_file = data_dir / "dataPaths.json"
    if not paths_file.exists():
        raise DataError("dataPaths.json not found", path=str(paths_file))
    paths = _read_json(paths_file)
    try:
        pc_paths = paths["pc"][key]
    except (KeyError, TypeError) as exc:
        raise UnsupportedVersion(
            f"no minecraft-data for version {key!r}",
            available=sorted(paths.get("pc", {}))[:20],
        ) from exc
    if isinstance(pc_paths, dict) and key not in pc_paths:
        # Some upstream layouts nest an edition dictionary again.
        pc_paths = next((value for value in pc_paths.values() if isinstance(value, dict)), pc_paths)
    if not isinstance(pc_paths, dict):
        raise DataError("malformed dataPaths.json entry", version=key, entry=pc_paths)

    def file_dir(file_key: str) -> Path:
        relative = pc_paths.get(file_key, f"pc/{key}")
        if not isinstance(relative, str):
            raise DataError("malformed file path", version=key, file=file_key)
        return data_dir / relative

    version_raw = _read_json(file_dir("version") / "version.json")
    version_json = msgspec.convert(version_raw, type=VersionJson)
    info = VersionInfo(
        key=key,
        minecraft_version=version_json.minecraftVersion,
        protocol=version_json.version,
        major_version=version_json.majorVersion,
    )
    features = Features.for_version(key)

    blocks_json = _decode_list(file_dir("blocks") / "blocks.json", BlockJson)
    items_json = _decode_list(file_dir("items") / "items.json", ItemJson)
    entities_json = _decode_list(file_dir("entities") / "entities.json", EntityJson)
    biomes_json = _decode_list(file_dir("biomes") / "biomes.json", BiomeJson)
    effects_json = _decode_list(file_dir("effects") / "effects.json", EffectJson)
    foods_json = _decode_list(file_dir("foods") / "foods.json", FoodJson)
    shapes_raw = _read_json(file_dir("blockCollisionShapes") / "blockCollisionShapes.json")
    shapes_json = msgspec.convert(shapes_raw, type=CollisionShapesJson)

    protocol_raw = _read_json(file_dir("protocol") / "protocol.json")
    if not isinstance(protocol_raw, dict):
        raise DataError("protocol.json must contain an object", version=key)

    return McData(
        version=info,
        features=replace(features, version=normalize(key), protocol=version_json.version),
        blocks=BlockRegistry.from_json(blocks_json),
        items=ItemRegistry.from_json(items_json),
        entities=EntityRegistry.from_json(entities_json),
        biomes=BiomeRegistry.from_json(biomes_json),
        effects=EffectRegistry.from_json(effects_json),
        foods=FoodRegistry.from_json(foods_json),
        shapes=ShapeTable.from_json(shapes_json),
        protocol=ProtocolSchema.from_json(protocol_raw),
    )


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataError("cannot read data file", path=str(path), reason=str(exc)) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataError("invalid JSON in data file", path=str(path), reason=str(exc)) from exc


def _decode_list(path: Path, struct_type: Any) -> list[Any]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise DataError("expected a JSON array", path=str(path))
    try:
        return msgspec.convert(raw, type=list[struct_type])
    except msgspec.ValidationError as exc:
        raise DataError("invalid data schema", path=str(path), reason=str(exc)) from exc
