"""Cross-layer Protocols (ADR-2).

Upper layers depend on these structural interfaces, never on concrete lower-layer classes. They are
runtime-checkable so tests can assert conformance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pyflayer.models.vec3 import BlockPos, ChunkPos

__all__ = ["WorldReader", "ActionHost", "PacketSink", "Dispatcher", "BlockMatcher"]


class BlockMatcher(Protocol):
    """Predicate over a block state id (or a block name for legacy versions)."""

    def __call__(self, block_state_id: int) -> bool: ...


@runtime_checkable
class WorldReader(Protocol):
    """Read-only world access used by physics, pathfinding and actions."""

    min_y: int
    height: int

    def block_state_id(self, pos: BlockPos) -> int: ...

    def block_state_id_or(self, pos: BlockPos, default: int) -> int: ...

    def is_loaded(self, pos: ChunkPos) -> bool: ...


@runtime_checkable
class PacketSink(Protocol):
    """Anything that can accept an outbound packet object."""

    async def send(self, packet: object) -> None: ...


@runtime_checkable
class Dispatcher(Protocol):
    """Minimal event emission surface available to every layer."""

    def dispatch(self, event: object) -> None: ...


class ActionHost(Protocol):
    """Facade implemented by ``Bot`` for actions (finalized in M6)."""

    world: WorldReader

    async def send(self, packet: object) -> None: ...

    @property
    def position(self) -> Sequence[float]: ...

    def __getattr__(self, name: str) -> Any: ...
