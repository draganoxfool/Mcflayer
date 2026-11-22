"""msgspec Struct definitions for the ``minecraft-data`` JSON subset.

Only the fields PyFlayer reads are declared; unknown keys are ignored by msgspec. All structs are
immutable, so an ``McData`` snapshot is safe to share across tasks and worker threads (ADR-6).
"""

from __future__ import annotations

import msgspec

__all__ = [
    "BiomeJson",
    "BlockJson",
    "BlockVariationJson",
    "CollisionShapesJson",
    "EffectJson",
    "EntityJson",
    "FoodJson",
    "ItemJson",
    "ItemVariationJson",
    "VersionJson",
]


class BlockVariationJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """One block metadata variation (1.8-style data)."""

    metadata: int = 0
    displayName: str = ""
    description: str = ""


class BlockJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """A block entry as stored in ``blocks.json``."""

    id: int
    name: str
    displayName: str = ""
    hardness: float | None = None
    resistance: float = 0.0
    stackSize: int = 64
    diggable: bool = True
    transparent: bool = False
    emitLight: int = 0
    filterLight: int = 0
    boundingBox: str = "block"
    material: str | None = None
    variations: tuple[BlockVariationJson, ...] = ()
    minStateId: int | None = None
    maxStateId: int | None = None
    defaultState: int | None = None


class ItemVariationJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """An item metadata variation."""

    metadata: int = 0
    displayName: str = ""


class ItemJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """An item entry as stored in ``items.json``."""

    id: int
    name: str
    displayName: str = ""
    stackSize: int = 64
    maxDurability: int | None = None
    variations: tuple[ItemVariationJson, ...] = ()


class EntityJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """An entity entry."""

    id: int
    name: str
    displayName: str = ""
    type: str = "other"
    category: str = "Generic"
    width: float | None = None
    height: float | None = None


class BiomeJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """A biome entry."""

    id: int
    name: str
    displayName: str = ""
    name_legacy: str | None = None
    category: str = ""
    dimension: str = ""
    temperature: float = 0.5
    rainfall: float = 0.5
    depth: float = 0.0
    color: int = 0


class EffectJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """A status effect entry."""

    id: int
    name: str
    displayName: str = ""
    type: str = "good"


class FoodJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """A food entry."""

    id: int
    name: str
    displayName: str = ""
    stackSize: int = 64
    foodPoints: float = 0.0
    saturation: float = 0.0
    effectiveQuality: float = 0.0
    saturationRatio: float = 0.0


class VersionJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """``version.json`` contents."""

    version: int
    minecraftVersion: str
    majorVersion: str


class CollisionShapesJson(msgspec.Struct, frozen=True, omit_defaults=True):
    """``blockCollisionShapes.json`` contents."""

    blocks: dict[str, int | list[int]]
    shapes: dict[str, list[list[float]]]
