"""Data-driven Minecraft registries and feature flags (``minecraft-data``)."""

from __future__ import annotations

from pyflayer.data.features import Features
from pyflayer.data.loader import McData, ProtocolSchema, default_data_dir
from pyflayer.data.registries import (
    Biome,
    BiomeRegistry,
    Block,
    BlockRegistry,
    Effect,
    EffectRegistry,
    Entity,
    EntityRegistry,
    Food,
    FoodRegistry,
    Item,
    ItemRegistry,
    Registry,
)
from pyflayer.data.shapes import ShapeTable
from pyflayer.data.versions import (
    VersionInfo,
    protocol_for,
    version_for_protocol,
    version_key,
)

__all__ = [
    "Biome",
    "BiomeRegistry",
    "Block",
    "BlockRegistry",
    "Effect",
    "EffectRegistry",
    "Entity",
    "EntityRegistry",
    "Features",
    "Food",
    "FoodRegistry",
    "Item",
    "ItemRegistry",
    "McData",
    "ProtocolSchema",
    "Registry",
    "ShapeTable",
    "VersionInfo",
    "default_data_dir",
    "protocol_for",
    "version_for_protocol",
    "version_key",
]
