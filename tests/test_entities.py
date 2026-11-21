from __future__ import annotations

from pyflayer.data import McData
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import Vec3
from pyflayer.world.entities import EntityTracker

MC = McData.load("1.8.9")


def test_spawn_uses_registry_type_name() -> None:
    tracker = EntityTracker(MC)
    entity = tracker.spawn(1, type_id=1, position=Vec3(1.0, 2.0, 3.0))
    assert entity.type_name is not None
    assert tracker.get(1) is entity
    assert len(tracker) == 1


def test_spawn_player_and_lookups() -> None:
    tracker = EntityTracker(MC)
    entity = tracker.spawn(
        7,
        type_name="player",
        uuid="00000000-0000-0000-0000-000000000001",
        position=Vec3(0.5, 64.0, 0.5),
        name="Steve",
    )
    assert entity.is_player
    assert tracker.by_uuid(entity.uuid or "") is entity
    assert tracker.set_name(entity.uuid or "", "Alex") is entity
    assert entity.name == "Alex"


def test_relative_move_look_teleport_and_velocity() -> None:
    tracker = EntityTracker(MC)
    tracker.spawn(2, type_name="zombie", position=Vec3(0.0, 64.0, 0.0))
    moved = tracker.move_relative(2, 32, -32, 16, on_ground=True)
    assert moved is not None
    assert moved.position == Vec3(1.0, 63.0, 0.5)
    assert moved.on_ground
    tracker.look(2, 64, -64)
    assert round(moved.yaw) == 90
    assert round(moved.pitch) == -90
    tracker.move_look(2, 0, 32, 0, 128, 0)
    assert moved.position.y == 64.0
    assert round(moved.yaw) == 180
    tracker.teleport(2, Vec3(10.0, 70.0, -5.0), yaw=0, pitch=0)
    assert moved.position == Vec3(10.0, 70.0, -5.0)
    tracker.set_velocity(2, (8000, 0, -4000))
    assert moved.velocity == Vec3(1.0, 0.0, -0.5)
    tracker.set_head_yaw(2, 32)
    assert moved.head_yaw == 45.0


def test_metadata_equipment_attach_and_remove() -> None:
    tracker = EntityTracker(MC)
    tracker.spawn(3, type_name="player", uuid="u1")
    tracker.set_metadata(3, {0: 1, 2: "hello"})
    entity = tracker.get(3)
    assert entity is not None and entity.metadata == {0: 1, 2: "hello"}
    tracker.set_metadata(3, {3: 4})
    assert entity.metadata == {0: 1, 2: "hello", 3: 4}
    item = ItemStack(item_id=1, count=1)
    tracker.set_equipment(3, 0, item)
    assert entity.equipment[0] is item
    tracker.attach(3, 99, leash=False)
    assert entity.vehicle_id == 99

    tracker.spawn(4, type_name="item")
    removed = tracker.remove_many([3, 4, 5])
    assert {entity.entity_id for entity in removed} == {3, 4}
    assert tracker.get(3) is None
    assert tracker.by_uuid("u1") is None
    assert len(tracker) == 0


def test_clear_and_unknown_updates() -> None:
    tracker = EntityTracker(MC)
    tracker.spawn(1, type_name="player", uuid="u")
    tracker.clear()
    assert len(tracker) == 0
    assert tracker.move_relative(1, 1, 1, 1) is None
    assert tracker.look(1, 1, 1) is None
    assert tracker.teleport(1, Vec3(0, 0, 0)) is None
    assert tracker.set_metadata(1, {}) is None
    assert tracker.set_equipment(1, 0, ItemStack()) is None
