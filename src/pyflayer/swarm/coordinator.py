"""Lightweight cooperation primitives for a bot cluster.

Three pieces:

* :class:`ClaimRegistry` — TTL claims over blocks or box regions so two bots never mine or build
  the same spot. Claims are owned by a bot name and release automatically on death/disconnect.
* :class:`Blackboard` — a typed key/value store with change events, used to share discoveries
  ("found_diamonds", "base_chest") between bots.
* :class:`PathCache` — an LRU cache of planner results keyed by world/start/goal (M6 fills it; the
  cache itself is version-aware and can invalidate a whole world when a block changes).

All time comes from the injected :class:`~pyflayer._internal.clock.Clock`.

Examples:
    >>> claims = ClaimRegistry()
    >>> claims.claim("Miner1", BlockPos(10, 64, 10))
    True
    >>> claims.claim("Miner2", BlockPos(10, 64, 10))
    False
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable, Iterator
from dataclasses import dataclass

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.events.base import Event
from pyflayer.events.bus import EventBus
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.world.store import WorldKey

__all__ = [
    "Blackboard",
    "BlackboardChangedEvent",
    "Claim",
    "ClaimRegistry",
    "PathCache",
    "PathCacheStats",
    "RegionClaim",
    "RoleRegistry",
]


@dataclass(frozen=True, slots=True)
class Claim:
    """A claim on a single block."""

    owner: str
    pos: BlockPos
    expires_at: float | None = None
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class RegionClaim:
    """A claim on an inclusive box of blocks."""

    owner: str
    minimum: BlockPos
    maximum: BlockPos
    expires_at: float | None = None
    tag: str | None = None

    def contains(self, pos: BlockPos) -> bool:
        """True when ``pos`` lies inside the box."""
        return (
            self.minimum.x <= pos.x <= self.maximum.x
            and self.minimum.y <= pos.y <= self.maximum.y
            and self.minimum.z <= pos.z <= self.maximum.z
        )


class ClaimRegistry:
    """Block and region claims with TTL.

    Args:
        clock: Injected clock; TTLs are measured on it.
        max_region_volume: Reject region claims larger than this many blocks (default 65536) so a
            typo cannot allocate an unbounded box.
    """

    __slots__ = ("_blocks", "_regions", "_version", "clock", "max_region_volume")

    def __init__(self, *, clock: Clock | None = None, max_region_volume: int = 65536) -> None:
        self.clock = clock or MonotonicClock()
        self.max_region_volume = max_region_volume
        self._blocks: dict[BlockPos, Claim] = {}
        self._regions: list[RegionClaim] = []
        self._version = 0

    @property
    def version(self) -> int:
        """Increments on every successful claim/release/expiry."""
        return self._version

    # ------------------------------------------------------------------ claims
    def claim(
        self,
        owner: str,
        pos: BlockPos,
        *,
        ttl: float | None = None,
        tag: str | None = None,
    ) -> bool:
        """Claim one block; ``False`` when another owner already holds it."""
        self.expire()
        current = self.owner_of(pos)
        if current is not None and current != owner:
            return False
        self._blocks[pos] = Claim(owner, pos, self._deadline(ttl), tag)
        self._version += 1
        return True

    def claim_region(
        self,
        owner: str,
        minimum: BlockPos,
        maximum: BlockPos,
        *,
        ttl: float | None = None,
        tag: str | None = None,
    ) -> bool:
        """Claim an inclusive box all-or-nothing.

        Returns:
            ``True`` when the whole box was claimed; ``False`` when any part is held by another
            owner or the box exceeds ``max_region_volume``.
        """
        self.expire()
        low = BlockPos(
            min(minimum.x, maximum.x), min(minimum.y, maximum.y), min(minimum.z, maximum.z)
        )
        high = BlockPos(
            max(minimum.x, maximum.x), max(minimum.y, maximum.y), max(minimum.z, maximum.z)
        )
        volume = (high.x - low.x + 1) * (high.y - low.y + 1) * (high.z - low.z + 1)
        if volume > self.max_region_volume:
            return False
        for pos, claim in self._blocks.items():
            if claim.owner == owner:
                continue
            if low.x <= pos.x <= high.x and low.y <= pos.y <= high.y and low.z <= pos.z <= high.z:
                return False
        for region in self._regions:
            if region.owner == owner:
                continue
            if _boxes_overlap(low, high, region.minimum, region.maximum):
                return False
        self._regions.append(RegionClaim(owner, low, high, self._deadline(ttl), tag))
        self._version += 1
        return True

    def release(self, owner: str, pos: BlockPos) -> bool:
        """Release a block claim held by ``owner``."""
        claim = self._blocks.get(pos)
        if claim is None or claim.owner != owner:
            return False
        del self._blocks[pos]
        self._version += 1
        return True

    def release_region(self, owner: str, pos: BlockPos) -> bool:
        """Release the first region claim held by ``owner`` that contains ``pos``."""
        for index, region in enumerate(self._regions):
            if region.owner == owner and region.contains(pos):
                del self._regions[index]
                self._version += 1
                return True
        return False

    def release_owner(self, owner: str) -> int:
        """Release every block and region claim of ``owner``; return the removed count."""
        removed = [pos for pos, claim in self._blocks.items() if claim.owner == owner]
        for pos in removed:
            del self._blocks[pos]
        regions = [region for region in self._regions if region.owner == owner]
        self._regions = [region for region in self._regions if region.owner != owner]
        count = len(removed) + len(regions)
        if count:
            self._version += 1
        return count

    def owner_of(self, pos: BlockPos) -> str | None:
        """Owner of the claim covering ``pos``, if any."""
        self.expire()
        claim = self._blocks.get(pos)
        if claim is not None:
            return claim.owner
        for region in self._regions:
            if region.contains(pos):
                return region.owner
        return None

    def is_claimed(self, pos: BlockPos, *, by: str | None = None) -> bool:
        """True when ``pos`` is claimed (optionally by a specific owner)."""
        owner = self.owner_of(pos)
        return owner is not None if by is None else owner == by

    def claims(self) -> tuple[Claim, ...]:
        """Snapshot of block claims."""
        return tuple(self._blocks.values())

    def regions(self) -> tuple[RegionClaim, ...]:
        """Snapshot of region claims."""
        return tuple(self._regions)

    # ------------------------------------------------------------------ expiry
    def expire(self) -> int:
        """Drop expired claims; return how many were removed."""
        now = self.clock.monotonic()
        expired_blocks = [
            pos
            for pos, claim in self._blocks.items()
            if claim.expires_at is not None and claim.expires_at <= now
        ]
        for pos in expired_blocks:
            del self._blocks[pos]
        before = len(self._regions)
        self._regions = [
            region
            for region in self._regions
            if region.expires_at is None or region.expires_at > now
        ]
        removed = len(expired_blocks) + (before - len(self._regions))
        if removed:
            self._version += 1
        return removed

    def _deadline(self, ttl: float | None) -> float | None:
        if ttl is None:
            return None
        return self.clock.monotonic() + ttl

    def __len__(self) -> int:
        self.expire()
        return len(self._blocks) + len(self._regions)

    def __repr__(self) -> str:
        return f"ClaimRegistry(blocks={len(self._blocks)}, regions={len(self._regions)})"


@dataclass(frozen=True, slots=True)
class BlackboardChangedEvent(Event):
    """A blackboard value was set or deleted."""

    key: str
    value: object
    previous: object = None
    owner: str = ""
    version: int = 0


class Blackboard:
    """Typed key/value shared state with change events.

    Args:
        clock: Injected clock for optional entry TTLs.
    """

    __slots__ = ("_bus", "_expiry", "_values", "_version", "clock")

    def __init__(self, *, clock: Clock | None = None) -> None:
        self.clock = clock or MonotonicClock()
        self._bus = EventBus(clock=self.clock)
        self._values: dict[str, object] = {}
        self._expiry: dict[str, float] = {}
        self._version = 0

    @property
    def events(self) -> EventBus:
        """Bus carrying :class:`BlackboardChangedEvent`."""
        return self._bus

    @property
    def version(self) -> int:
        """Increments on every change."""
        return self._version

    def set(
        self,
        key: str,
        value: object,
        *,
        owner: str = "",
        ttl: float | None = None,
    ) -> int:
        """Store ``value`` and dispatch a change event; return the new version."""
        self._purge()
        previous = self._values.get(key)
        self._values[key] = value
        if ttl is None:
            self._expiry.pop(key, None)
        else:
            self._expiry[key] = self.clock.monotonic() + ttl
        self._version += 1
        self._bus.dispatch(
            BlackboardChangedEvent(key, value, previous, owner, self._version)
        )
        return self._version

    def update(self, values: dict[str, object], *, owner: str = "") -> int:
        """Store several values; every key gets its own change event."""
        version = self._version
        for key, value in values.items():
            version = self.set(key, value, owner=owner)
        return version

    def get(self, key: str, default: object = None) -> object:
        """Value for ``key`` or ``default``."""
        self._purge()
        return self._values.get(key, default)

    def delete(self, key: str, *, owner: str = "") -> bool:
        """Remove ``key``; returns ``False`` when it was absent."""
        self._purge()
        if key not in self._values:
            return False
        previous = self._values.pop(key)
        self._expiry.pop(key, None)
        self._version += 1
        self._bus.dispatch(
            BlackboardChangedEvent(key, None, previous, owner, self._version)
        )
        return True

    def clear(self) -> None:
        """Remove every entry without dispatching per-key events."""
        self._values.clear()
        self._expiry.clear()
        self._version += 1

    def snapshot(self) -> dict[str, object]:
        """Copy of the current values."""
        self._purge()
        return dict(self._values)

    async def wait_for(
        self, key: str, *, timeout: float | None = None  # noqa: ASYNC109 - public event-wait API
    ) -> object:
        """Wait for the next event for ``key`` and return its value."""

        event = await self._bus.wait_for(
            BlackboardChangedEvent,
            check=lambda candidate: candidate.key == key,
            timeout=timeout,
        )
        return event.value

    def _purge(self) -> None:
        now = self.clock.monotonic()
        expired = [key for key, deadline in self._expiry.items() if deadline <= now]
        for key in expired:
            self._expiry.pop(key, None)
            self._values.pop(key, None)

    def __len__(self) -> int:
        self._purge()
        return len(self._values)

    def __contains__(self, key: str) -> bool:
        self._purge()
        return key in self._values

    def __repr__(self) -> str:
        return f"Blackboard(keys={len(self._values)}, version={self._version})"


@dataclass(frozen=True, slots=True)
class PathCacheStats:
    """Hit/miss counters for :class:`PathCache`."""

    hits: int = 0
    misses: int = 0
    entries: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """Hits divided by all lookups (``0.0`` before the first lookup)."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class PathCache:
    """Small LRU cache for planner results.

    Keys are opaque and hashable; :meth:`make_key` provides the conventional
    ``(world, start, goal, world_version)`` tuple. Block changes can invalidate one world or the
    whole cache.

    Args:
        max_entries: Maximum cached paths (oldest used entry is evicted).
    """

    __slots__ = ("_entries", "_evictions", "_hits", "_misses", "max_entries")

    def __init__(self, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, object] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @staticmethod
    def make_key(
        world: WorldKey,
        start: BlockPos | Vec3,
        goal: object,
        *,
        version: int = 0,
    ) -> tuple[object, ...]:
        """Build the conventional path-cache key."""
        return (
            world.server,
            world.dimension,
            _point(start),
            _point(goal),
            version,
        )

    def get(self, key: Hashable) -> object | None:
        """Cached value or ``None`` (counted as a miss)."""
        if key not in self._entries:
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return self._entries[key]

    def put(self, key: Hashable, value: object) -> None:
        """Insert or refresh a cache entry, evicting the least recently used entry."""
        if key in self._entries:
            self._entries[key] = value
            self._entries.move_to_end(key)
            return
        self._entries[key] = value
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def invalidate(self, key: Hashable) -> bool:
        """Drop one key; returns whether it was present."""
        return self._entries.pop(key, None) is not None

    def invalidate_world(self, world: WorldKey) -> int:
        """Drop every entry for ``world``; return the number removed."""
        keys = [
            key
            for key in self._entries
            if isinstance(key, tuple)
            and len(key) >= 2
            and key[0] == world.server
            and key[1] == world.dimension
        ]
        for key in keys:
            del self._entries[key]
        return len(keys)

    def clear(self) -> None:
        """Drop every entry (counters are kept)."""
        self._entries.clear()

    @property
    def stats(self) -> PathCacheStats:
        """Current counters."""
        return PathCacheStats(self._hits, self._misses, len(self._entries), self._evictions)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Hashable]:
        return iter(self._entries)

    def __repr__(self) -> str:
        return f"PathCache(entries={len(self._entries)}, max={self.max_entries})"


class RoleRegistry:
    """Assign at most one role per bot, with reverse lookup."""

    __slots__ = ("_roles",)

    def __init__(self) -> None:
        self._roles: dict[str, str] = {}

    def assign(self, bot: str, role: str) -> None:
        """Give ``bot`` a role (replacing its previous one)."""
        self._roles[bot] = role

    def role_of(self, bot: str) -> str | None:
        """Role of ``bot``, if assigned."""
        return self._roles.get(bot)

    def holders(self, role: str) -> tuple[str, ...]:
        """Bots currently assigned ``role``."""
        return tuple(bot for bot, assigned in self._roles.items() if assigned == role)

    def release(self, bot: str) -> bool:
        """Remove ``bot`` from the registry."""
        return self._roles.pop(bot, None) is not None

    def clear(self) -> None:
        """Remove every assignment."""
        self._roles.clear()

    def snapshot(self) -> dict[str, str]:
        """Copy of bot-to-role assignments."""
        return dict(self._roles)

    def __len__(self) -> int:
        return len(self._roles)


def _point(value: object) -> tuple[object, object, object]:
    if isinstance(value, BlockPos):
        return (value.x, value.y, value.z)
    if isinstance(value, Vec3):
        return (round(value.x, 3), round(value.y, 3), round(value.z, 3))
    return (type(value).__name__, repr(value), 0)


def _boxes_overlap(
    low_a: BlockPos, high_a: BlockPos, low_b: BlockPos, high_b: BlockPos
) -> bool:
    return not (
        high_a.x < low_b.x
        or high_b.x < low_a.x
        or high_a.y < low_b.y
        or high_b.y < low_a.y
        or high_a.z < low_b.z
        or high_b.z < low_a.z
    )
