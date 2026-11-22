"""Collision shape tables.

``minecraft-data`` stores collision boxes separately from blocks:

* ``blocks``: block name -> shape id, or a list indexed by metadata for 1.8-style blocks.
* ``shapes``: shape id -> list of ``[min_x, min_y, min_z, max_x, max_y, max_z]`` boxes.

The table precomputes :class:`AABB` tuples so the physics engine never parses JSON at runtime.
Modern global block-state ids (1.13+) are resolved to a block and metadata in M3; M1 exposes the
legacy (1.8) path and a name-based path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pyflayer.data.registries import BlockRegistry
from pyflayer.data.schema import CollisionShapesJson
from pyflayer.models.aabb import AABB

__all__ = ["SHAPE_EMPTY", "SHAPE_FULL_BLOCK", "ShapeTable"]

SHAPE_EMPTY: tuple[AABB, ...] = ()
SHAPE_FULL_BLOCK: tuple[AABB, ...] = (AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)


@dataclass(frozen=True, slots=True)
class ShapeTable:
    """Immutable collision lookup."""

    blocks: Mapping[str, int | tuple[int, ...]]
    shapes: Mapping[int, tuple[AABB, ...]]

    @classmethod
    def from_json(cls, data: CollisionShapesJson) -> ShapeTable:
        """Build from decoded ``blockCollisionShapes.json``."""
        blocks: dict[str, int | tuple[int, ...]] = {}
        for name, value in data.blocks.items():
            blocks[name] = value if isinstance(value, int) else tuple(value)
        shapes: dict[int, tuple[AABB, ...]] = {}
        for shape_id, boxes in data.shapes.items():
            shapes[int(shape_id)] = tuple(
                AABB(box[0], box[1], box[2], box[3], box[4], box[5]) for box in boxes
            )
        return cls(blocks, shapes)

    def shape_id(self, name: str, metadata: int = 0) -> int:
        """Shape id for a block name/metadata; ``0`` (empty) when unknown."""
        value = self.blocks.get(name.removeprefix("minecraft:").lower(), 0)
        if isinstance(value, tuple):
            if not value:
                return 0
            return value[metadata] if 0 <= metadata < len(value) else value[0]
        return value

    def boxes_for(self, name: str, metadata: int = 0) -> tuple[AABB, ...]:
        """Collision boxes for a named block."""
        return self.shapes.get(self.shape_id(name, metadata), SHAPE_EMPTY)

    def boxes_for_state(self, state_id: int, blocks: BlockRegistry) -> tuple[AABB, ...]:
        """Collision boxes for a legacy or modern global block-state id."""
        block, metadata = blocks.from_state_id(state_id)
        return self.boxes_for(block.name, metadata)

    def boxes_for_legacy_state(self, state_id: int, blocks: BlockRegistry) -> tuple[AABB, ...]:
        """Backward-compatible alias for :meth:`boxes_for_state`."""
        return self.boxes_for_state(state_id, blocks)

    def state_count(self) -> int:
        """Number of collision-shaped block entries."""
        return len(self.blocks)
