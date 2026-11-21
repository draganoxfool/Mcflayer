"""Block states exposed by the world layer.

For 1.8 a state id is ``(block_id << 4) | metadata``. :class:`BlockState` resolves that to the block
registry entry and keeps the metadata, so callers can ask for a human name, collision boxes or
whether the block is air without touching the protocol.

Examples:
    >>> state = BlockState.from_legacy(16, McData.load("1.8.9"))  # doctest: +SKIP
    >>> state.name
    'stone'
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.data.loader import McData
from pyflayer.data.registries import Block
from pyflayer.models.aabb import AABB

__all__ = ["BlockState"]


@dataclass(frozen=True, slots=True)
class BlockState:
    """A resolved block state."""

    state_id: int
    block_id: int
    metadata: int
    name: str
    block: Block | None = None

    @property
    def is_air(self) -> bool:
        """True for air (state 0 / block id 0)."""
        return self.block_id == 0

    def collision_boxes(self, mc: McData) -> tuple[AABB, ...]:
        """Collision boxes for this state."""
        if self.block is None:
            return ()
        return mc.shapes.boxes_for(self.block.name, self.metadata)

    @classmethod
    def from_legacy(cls, state_id: int, mc: McData) -> BlockState:
        """Resolve a 1.8 state id against a data snapshot (unknown ids stay name-less)."""
        state_id = int(state_id)
        block_id, metadata = state_id >> 4, state_id & 0x0F
        block = mc.blocks.get(block_id)
        return cls(
            state_id=state_id,
            block_id=block_id,
            metadata=metadata,
            name=block.name if block is not None else f"unknown:{block_id}",
            block=block,
        )
