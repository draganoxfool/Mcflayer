"""Immutable registries with name/id lookups.

Registries are tuples plus precomputed dicts; they are built once per version and never mutated.
Legacy (pre-1.13) block state ids are ``(block_id << 4) | metadata`` helpers, not a global table.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

from pyflayer.data.schema import BiomeJson, BlockJson, EffectJson, EntityJson, FoodJson, ItemJson
from pyflayer.errors import MissingRegistryEntry

__all__ = [
    "Biome",
    "BiomeRegistry",
    "Block",
    "BlockRegistry",
    "Effect",
    "EffectRegistry",
    "Entity",
    "EntityRegistry",
    "Food",
    "FoodRegistry",
    "Item",
    "ItemRegistry",
    "Registry",
]

T = TypeVar("T")


def _normalize_name(name: str) -> str:
    name = name.strip().lower()
    return name.removeprefix("minecraft:")


class Registry(Generic[T]):
    """Frozen name/id registry built from entries exposing ``id`` and ``name``."""

    __slots__ = ("_by_id", "_by_name", "_entries")

    def __init__(self, entries: Iterable[T]) -> None:
        self._entries: tuple[T, ...] = tuple(entries)
        self._by_name: dict[str, T] = {}
        self._by_id: dict[int, T] = {}
        for entry in self._entries:
            name = _normalize_name(getattr(entry, "name"))  # noqa: B009 - structural entry type
            entry_id = int(getattr(entry, "id"))  # noqa: B009
            self._by_name.setdefault(name, entry)
            self._by_id.setdefault(entry_id, entry)

    def __iter__(self) -> Iterator[T]:
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
    min_state_id: int = 0
    max_state_id: int = 0
    default_state_id: int = 0


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
    food_points: float
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
        min_state_id=entry.minStateId or 0,
        max_state_id=entry.maxStateId or 0,
        default_state_id=entry.defaultState or 0,
    )


class BlockRegistry(Registry[Block]):
    """Block registry with legacy and modern global-state lookup.

    Pre-1.13 state ids are ``(block_id << 4) | metadata``. 1.13+ assigns every block property
    combination a contiguous global id; this registry indexes those ranges so a decoded chunk state
    resolves to the right block without a per-block JSON scan.
    """

    __slots__ = ("_by_legacy_id", "_by_state", "_modern")

    def __init__(self, entries: Iterable[Block], *, modern: bool = False) -> None:
        super().__init__(entries)
        self._by_legacy_id = {block.id: block for block in self._entries}
        self._modern = modern
        self._by_state: tuple[Block | None, ...] = ()
        if modern and self._entries:
            size = max(block.max_state_id for block in self._entries) + 1
            table: list[Block | None] = [None] * size
            for block in self._entries:
                for state_id in range(block.min_state_id, block.max_state_id + 1):
                    table[state_id] = block
            self._by_state = tuple(table)

    @classmethod
    def from_json(cls, entries: Iterable[BlockJson]) -> BlockRegistry:
        """Build from decoded ``blocks.json`` entries."""
        decoded = list(entries)
        modern = any(entry.minStateId is not None for entry in decoded)
        return cls((_block(entry) for entry in decoded), modern=modern)

    @property
    def modern(self) -> bool:
        """True for a 1.13+ global block-state registry."""
        return self._modern

    def from_state_id(self, state_id: int) -> tuple[Block, int]:
        """Resolve a global block-state id to ``(block, metadata)``.

        For modern data ``metadata`` is the offset inside the block's state range. Legacy 1.8 state
        ids keep their original ``(block_id << 4) | meta`` meaning.
        """
        state_id = int(state_id)
        if self._modern:
            if 0 <= state_id < len(self._by_state):
                block = self._by_state[state_id]
                if block is not None:
                    return block, state_id - block.min_state_id
            raise MissingRegistryEntry(
                f"no block for state id {state_id}", registry="blocks", key=state_id
            )
        return self.from_legacy_state_id(state_id)

    def block_for_state(self, state_id: int) -> Block | None:
        """Block for a global state id, or ``None`` when unknown/legacy."""
        if not self._modern or not 0 <= int(state_id) < len(self._by_state):
            return None
        return self._by_state[int(state_id)]

    def state_range(self, name: str) -> tuple[int, int]:
        """Inclusive global state-id range for a block name.

        Legacy data has no global table, so the range is the block's legacy base state.
        """
        block = self[name]
        if self._modern:
            return block.min_state_id, block.max_state_id
        base = self.legacy_state_id(block.id)
        return base, base

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
        """State id for a block name.

        Modern data ignores ``metadata`` and returns the block's default global state. Legacy data
        keeps the ``(block_id << 4) | metadata`` packing.
        """
        block = self[name]
        if self._modern:
            return block.default_state_id or block.min_state_id
        return self.legacy_state_id(block.id, metadata)


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
