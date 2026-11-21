"""Entity tracking.

1.8 sends positions as fixed-point (1/32 block) and rotations as signed bytes (1/256 turn); the
tracker normalizes both to floats and degrees. Metadata is a decoded ``{key: value}`` mapping and
equipment is ``{slot: ItemStack}``.

Examples:
    >>> tracker = EntityTracker(McData.load("1.8.9"))
    >>> tracker.spawn(1, type_id=54, position=Vec3(0, 64, 0)).type_name
    'player'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pyflayer.data.loader import McData
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import Vec3

__all__ = ["Entity", "EntityTracker", "POSITION_SCALE", "ROTATION_SCALE"]

POSITION_SCALE = 1.0 / 32.0
ROTATION_SCALE = 360.0 / 256.0
VELOCITY_SCALE = 1.0 / 8000.0


@dataclass(slots=True)
class Entity:
    """A tracked entity or player."""

    entity_id: int
    type_id: int | None = None
    type_name: str | None = None
    uuid: str | None = None
    name: str | None = None
    position: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    yaw: float = 0.0
    pitch: float = 0.0
    head_yaw: float = 0.0
    velocity: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.0, 0.0))
    on_ground: bool = False
    metadata: dict[int, Any] = field(default_factory=dict)
    equipment: dict[int, ItemStack] = field(default_factory=dict)
    vehicle_id: int | None = None
    mount: int | None = None

    @property
    def block_pos(self):
        """Block containing the entity."""
        return self.position.floored()

    @property
    def is_player(self) -> bool:
        """True when this entity carries a player UUID."""
        return self.uuid is not None

    def __repr__(self) -> str:
        return (
            f"Entity(id={self.entity_id}, type={self.type_name!r}, "
            f"pos={self.position})"
        )


class EntityTracker:
    """Owns all entities visible to one bot."""

    __slots__ = ("mc", "entities", "_by_uuid")

    def __init__(self, mc: McData) -> None:
        self.mc = mc
        self.entities: dict[int, Entity] = {}
        self._by_uuid: dict[str, Entity] = {}

    def get(self, entity_id: int) -> Entity | None:
        """Entity by runtime id."""
        return self.entities.get(entity_id)

    def by_uuid(self, uuid: str) -> Entity | None:
        """Player entity by UUID."""
        return self._by_uuid.get(uuid)

    def all(self) -> tuple[Entity, ...]:
        """All tracked entities."""
        return tuple(self.entities.values())

    def __len__(self) -> int:
        return len(self.entities)

    def __contains__(self, entity_id: object) -> bool:
        return entity_id in self.entities

    # ------------------------------------------------------------------ spawn
    def spawn(
        self,
        entity_id: int,
        *,
        type_id: int | None = None,
        type_name: str | None = None,
        uuid: str | None = None,
        position: Vec3 = Vec3(0.0, 0.0, 0.0),
        yaw: float = 0.0,
        pitch: float = 0.0,
        head_yaw: float = 0.0,
        velocity: Vec3 = Vec3(0.0, 0.0, 0.0),
        metadata: dict[int, Any] | None = None,
        name: str | None = None,
    ) -> Entity:
        """Create or replace an entity."""
        if type_name is None and type_id is not None:
            entry = self.mc.entities.get(type_id)
            type_name = entry.name if entry is not None else f"unknown:{type_id}"
        entity = Entity(
            entity_id=entity_id,
            type_id=type_id,
            type_name=type_name,
            uuid=uuid,
            name=name,
            position=position,
            yaw=yaw,
            pitch=pitch,
            head_yaw=head_yaw,
            velocity=velocity,
            metadata=dict(metadata or {}),
        )
        previous = self.entities.get(entity_id)
        if previous is not None and previous.uuid:
            self._by_uuid.pop(previous.uuid, None)
        self.entities[entity_id] = entity
        if uuid:
            self._by_uuid[uuid] = entity
        return entity

    # ------------------------------------------------------------------ updates
    def move_relative(self, entity_id: int, dx: int, dy: int, dz: int, *, on_ground: bool = False) -> Entity | None:
        """Apply a relative move (1/32 block units)."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.position = Vec3(
            entity.position.x + dx * POSITION_SCALE,
            entity.position.y + dy * POSITION_SCALE,
            entity.position.z + dz * POSITION_SCALE,
        )
        entity.on_ground = on_ground
        return entity

    def look(self, entity_id: int, yaw: int, pitch: int, *, on_ground: bool = False) -> Entity | None:
        """Apply a rotation-only update."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.yaw = yaw * ROTATION_SCALE
        entity.pitch = pitch * ROTATION_SCALE
        entity.on_ground = on_ground
        return entity

    def move_look(
        self,
        entity_id: int,
        dx: int,
        dy: int,
        dz: int,
        yaw: int,
        pitch: int,
        *,
        on_ground: bool = False,
    ) -> Entity | None:
        """Apply a relative move plus rotation."""
        entity = self.move_relative(entity_id, dx, dy, dz, on_ground=on_ground)
        if entity is not None:
            entity.yaw = yaw * ROTATION_SCALE
            entity.pitch = pitch * ROTATION_SCALE
        return entity

    def teleport(
        self,
        entity_id: int,
        position: Vec3,
        *,
        yaw: float | None = None,
        pitch: float | None = None,
        on_ground: bool = False,
    ) -> Entity | None:
        """Apply an absolute position update."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.position = position
        if yaw is not None:
            entity.yaw = yaw * ROTATION_SCALE
        if pitch is not None:
            entity.pitch = pitch * ROTATION_SCALE
        entity.on_ground = on_ground
        return entity

    def set_velocity(self, entity_id: int, velocity: tuple[int, int, int]) -> Entity | None:
        """Apply a velocity packet (1/8000 block per tick units)."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.velocity = Vec3(
            velocity[0] * VELOCITY_SCALE,
            velocity[1] * VELOCITY_SCALE,
            velocity[2] * VELOCITY_SCALE,
        )
        return entity

    def set_metadata(self, entity_id: int, metadata: dict[int, Any]) -> Entity | None:
        """Merge a metadata update."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.metadata.update(metadata)
        return entity

    def set_equipment(self, entity_id: int, slot: int, item: ItemStack) -> Entity | None:
        """Record an equipment change."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.equipment[slot] = item
        return entity

    def set_head_yaw(self, entity_id: int, head_yaw: int) -> Entity | None:
        """Update the head yaw (1/256 turn units)."""
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.head_yaw = head_yaw * ROTATION_SCALE
        return entity

    def attach(self, entity_id: int, vehicle_id: int, *, leash: bool = False) -> Entity | None:
        """Record a vehicle attachment."""
        del leash
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        entity.vehicle_id = vehicle_id
        return entity

    def set_name(self, uuid: str, name: str) -> Entity | None:
        """Attach a player name once the tab list provides it."""
        entity = self._by_uuid.get(uuid)
        if entity is not None:
            entity.name = name
        return entity

    def remove(self, entity_id: int) -> Entity | None:
        """Remove an entity."""
        entity = self.entities.pop(entity_id, None)
        if entity is not None and entity.uuid:
            self._by_uuid.pop(entity.uuid, None)
        return entity

    def remove_many(self, entity_ids: list[int]) -> list[Entity]:
        """Remove several entities, returning the ones that existed."""
        removed = [entity for entity_id in entity_ids if (entity := self.remove(entity_id))]
        return removed

    def clear(self) -> None:
        """Drop all entities (dimension change / disconnect)."""
        self.entities.clear()
        self._by_uuid.clear()

    def __repr__(self) -> str:
        return f"EntityTracker(entities={len(self.entities)})"
