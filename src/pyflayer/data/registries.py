"""Immutable registries with name/id lookups.

Registries are tuples plus precomputed dicts; they are built once per version and never mutated.
Legacy (pre-1.13) block state ids are ``(block_id << 4) | metadata`` helpers, not a global table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, TypeVar

from pyflayer.data.schema import BiomeJson, BlockJson, EffectJson, EntityJson, FoodJson, ItemJson
from pyflayer.errors import MissingRegistryEntry

__all__ = [
    "Registry",
    "Block",
    "Item",
    "Entity",
    "Biome",
    "Effect",
    "Food",
    "BlockRegistry",
    "ItemRegistry",
    "EntityRegistry",
    "BiomeRegistry",
    "EffectRegistry",
    "FoodRegistry",
]

T = TypeVar("T")


def _normalize_name(name: str) -> str:
    name = name.strip().lower()
    return name.removeprefix("minecraft:")


class Registry(Generic[T]):
    """Frozen name/id registry built from entries exposing ``id`` and ``name``."""

    __slots__ = ("_entries", "_by_name", "_by_id")

    def __init__(self, entries: Iterable[T]) -> None:
        self._entries: tuple[T, ...] = tuple(entries)
        self._by_name: dict[str, T] = {}
        self._by_id: dict[int, T] = {}
        for entry in self._entries:
            name = _normalize_name(getattr(entry, "name"))  # noqa: B009 - structural entry type
            entry_id = int(getattr(entry, "id"))  # noqa: B009
            self._by_name.setdefault(name, entry)
            self._by_id.setdefault(entry_id, entry)

    def __iter__(self):
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, int):
            return key in self._by_id
        if isinstance(key, str):
            return _normalize_name(key) in self._by_name
        return False

    def __getitem__(self, key: str | int) -> T:
        if isinstance(key, int):
            try:
                return self._by_id[key]
            except KeyError as exc:
                raise MissingRegistryEntry(
                    f"no {type(self).__name__} with id {key}",
                    registry=type(self).__name__,
                    key=key,
                ) from exc
        try:
            return self._by_name[_normalize_name(key)]
        except KeyError as exc:
            raise MissingRegistryEntry(
                f"no {type(self).__name__} named {key!r}",
                registry=type(self).__name__,
                key=key,
            ) from exc

    def get(self, key: str | int, default: T | None = None) -> T | None:
        """Lookup that returns ``default`` instead of raising."""
        try:
            return self[key]
        except MissingRegistryEntry:
            return default

    def by_name(self) -> dict[str, T]:
        """A copy of the name index."""
        return dict(self._by_name)

    def by_id(self) -> dict[int, T]:
        """A copy of the id index."""
        return dict(self._by_id)

    def names(self) -> tuple[str, ...]:
        """All registered names, in data-file order."""
        return tuple(self._by_name)


@dataclass(frozen=True, slots=True)
class Block:
    """A block flyweight (cache one per state by id)."""

    id: int
    name: str
    display_name: str
    hardness: float
    resistance: float
    stack_size: int
    diggable: bool
    transparent: bool
    emit_light: int
    filter_light: int
    bounding_box: str


@dataclass(frozen=True, slots=True)
class Item:
    """An item."""

    id: int
    name: str
    display_name: str
    stack_size: int
    max_durability: int | None = None


@dataclass(frozen=True, slots=True)
class Entity:
    """An entity type."""

    id: int
    name: str
    display_name: str
    kind: str
    category: str
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True, slots=True)
class Biome:
    """A biome."""

    id: int
    name: str
    display_name: str
    category: str
    dimension: str
    temperature: float
    rainfall: float
    depth: float
    color: int


@dataclass(frozen=True, slots=True)
class Effect:
    """A status effect."""

    id: int
    name: str
    display_name: str
    kind: str


@dataclass(frozen=True, slots=True)
class Food:
    """A food item's nutrition data."""

    id: int
    name: str
    display_name: str
    stack_size: int
    food_points: int
    saturation: float
    effective_quality: float
    saturation_ratio: float


def _block(entry: BlockJson) -> Block:
    return Block(
        id=entry.id,
        name=entry.name,
        display_name=entry.displayName,
        hardness=entry.hardness if entry.hardness is not None else -1.0,
        resistance=entry.resistance,
        stack_size=entry.stackSize,
        diggable=entry.diggable,
        transparent=entry.transparent,
        emit_light=entry.emitLight,
        filter_light=entry.filterLight,
        bounding_box=entry.boundingBox,
    )


class BlockRegistry(Registry[Block]):
    """Block registry with legacy state helpers for pre-1.13 versions."""

    __slots__ = ("_by_legacy_id",)

    def __init__(self, entries: Iterable[Block]) -> None:
        super().__init__(entries)
        self._by_legacy_id = {block.id: block for block in self._entries}

    @classmethod
    def from_json(cls, entries: Iterable[BlockJson]) -> BlockRegistry:
        """Build from decoded ``blocks.json`` entries."""
        return cls(_block(entry) for entry in entries)

    def legacy_state_id(self, block_id: int, metadata: int = 0) -> int:
        """Pre-1.13 state packing: ``(block_id << 4) | (metadata & 0xF)``."""
        return (block_id << 4) | (metadata & 0xF)

    def from_legacy_state_id(self, state_id: int) -> tuple[Block, int]:
        """Split a pre-1.13 state id into ``(block, metadata)``."""
        block_id, metadata = state_id >> 4, state_id & 0xF
        try:
            return self._by_legacy_id[block_id], metadata
        except KeyError as exc:
            raise MissingRegistryEntry(
                f"no block with legacy id {block_id}", registry="blocks", key=state_id
            ) from exc

    def state_id(self, name: str, metadata: int = 0) -> int:
        """Legacy state id for a block name and metadata."""
        return self.legacy_state_id(self[name].id, metadata)


class ItemRegistry(Registry[Item]):
    """Item registry, with ``from_json`` support."""

    @classmethod
    def from_json(cls, entries: Iterable[ItemJson]) -> ItemRegistry:
        """Build from decoded ``items.json`` entries."""
        return cls(
            Item(
                id=entry.id,
                name=entry.name,
                display_name=entry.displayName,
                stack_size=entry.stackSize,
                max_durability=entry.maxDurability,
            )
            for entry in entries
        )


class EntityRegistry(Registry[Entity]):
    """Entity registry."""

    @classmethod
    def from_json(cls, entries: Iterable[EntityJson]) -> EntityRegistry:
        """Build from decoded ``entities.json`` entries."""
        return cls(
            Entity(
                id=entry.id,
                name=entry.name,
                display_name=entry.displayName,
                kind=entry.type,
                category=entry.category,
                width=entry.width,
                height=entry.height,
            )
            for entry in entries
        )


class BiomeRegistry(Registry[Biome]):
    """Biome registry."""

    @classmethod
    def from_json(cls, entries: Iterable[BiomeJson]) -> BiomeRegistry:
        """Build from decoded ``biomes.json`` entries."""
        return cls(
            Biome(
                id=entry.id,
                name=entry.name,
                display_name=entry.displayName,
                category=entry.category,
                dimension=entry.dimension,
                temperature=entry.temperature,
                rainfall=entry.rainfall,
                depth=entry.depth,
                color=entry.color,
            )
            for entry in entries
        )


class EffectRegistry(Registry[Effect]):
    """Status-effect registry."""

    @classmethod
    def from_json(cls, entries: Iterable[EffectJson]) -> EffectRegistry:
        """Build from decoded ``effects.json`` entries."""
        return cls(
            Effect(
                id=entry.id,
                name=entry.name,
                display_name=entry.displayName,
                kind=entry.type,
            )
            for entry in entries
        )


class FoodRegistry(Registry[Food]):
    """Food registry."""

    @classmethod
    def from_json(cls, entries: Iterable[FoodJson]) -> FoodRegistry:
        """Build from decoded ``foods.json`` entries."""
        return cls(
            Food(
                id=entry.id,
                name=entry.name,
                display_name=entry.displayName,
                stack_size=entry.stackSize,
                food_points=entry.foodPoints,
                saturation=entry.saturation,
                effective_quality=entry.effectiveQuality,
                saturation_ratio=entry.saturationRatio,
            )
            for entry in entries
        )
