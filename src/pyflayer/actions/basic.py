"""Core actions: look, go to, dig, place, equip, eat and attack.

Actions never talk to the protocol directly except through the host surface the bot already
exposes (``set_movement``, ``place_block``, ``break_block``, ``_send_play`` …). Movement and look
always go through ``lease.controls`` so the scheduler can revoke them.

Examples:
    >>> await bot.actions.equip("diamond_pickaxe")
    >>> await bot.actions.dig(BlockPos(10, 64, 10))
"""

from __future__ import annotations

import math
from typing import Any, Protocol, cast

from pyflayer.actions.base import Action, Lease, OnPreempt, Resource
from pyflayer.data.loader import McData
from pyflayer.errors import ActionFailed, NoPath
from pyflayer.events.catalog import PathStartedEvent
from pyflayer.models.enums import Face
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.pathfinder.executor import PathExecutor
from pyflayer.pathfinder.goals import Goal, GoalBlock, GoalFollow, GoalNear
from pyflayer.pathfinder.planner import Path, PathPlanner
from pyflayer.world.entities import Entity, EntityTracker

__all__ = [
    "ActionHost",
    "Attack",
    "Dig",
    "Eat",
    "Equip",
    "GoTo",
    "Look",
    "LookAt",
    "Place",
    "face_position",
]


class ActionHost(Protocol):
    """Bot surface used by the built-in actions."""

    position: Vec3 | None
    game_mode: int | None
    world: Any
    entities: EntityTracker
    inventory: Any
    clock: Any
    events: Any

    def set_movement(
        self,
        forward: float = 0.0,
        strafe: float = 0.0,
        *,
        sprint: bool = False,
        sneak: bool = False,
    ) -> None: ...

    def stop_movement(self) -> None: ...

    def look(self, *, yaw: float | None = None, pitch: float | None = None) -> None: ...

    def jump(self) -> None: ...

    async def select_hotbar(self, slot: int) -> None: ...

    async def use_item(self) -> None: ...

    async def place_block(self, pos: BlockPos, **kwargs: Any) -> None: ...

    async def break_block(self, pos: BlockPos, **kwargs: Any) -> None: ...

    async def swing_arm(self) -> None: ...

    async def click_slot(self, slot: int, **kwargs: Any) -> int: ...

    async def _send_play(self, name: str, fields: dict[str, object]) -> None: ...


def face_position(origin: Vec3, target: Vec3) -> tuple[float, float]:
    """Return ``(yaw, pitch)`` that faces ``target`` from ``origin``."""
    dx = target.x - origin.x
    dy = target.y - origin.y
    dz = target.z - origin.z
    yaw = math.degrees(math.atan2(-dx, dz))
    horizontal = math.hypot(dx, dz)
    pitch = -math.degrees(math.atan2(dy, horizontal)) if horizontal else 0.0
    return yaw, pitch


def _host_mc(host: ActionHost) -> McData:
    return cast(McData, host.world.mc)


class Look(Action[None]):
    """Set the look direction."""

    resources = Resource.LOOK
    name = "look"

    def __init__(self, yaw: float, pitch: float = 0.0) -> None:
        self.yaw = yaw
        self.pitch = pitch

    async def run(self, lease: Lease) -> None:
        lease.look(self.yaw, self.pitch)


class LookAt(Action[None]):
    """Look at a block, vector or entity."""

    resources = Resource.LOOK
    name = "look_at"

    def __init__(self, target: BlockPos | Vec3 | Entity) -> None:
        self.target = target

    async def run(self, lease: Lease) -> None:
        host = cast(ActionHost, lease.scheduler.host)
        origin = host.position
        if origin is None:
            raise ActionFailed("no position to look from", action=self.name)
        target = self.target
        if isinstance(target, Entity):
            point = target.position
        elif isinstance(target, BlockPos):
            point = target.to_vec3()
        else:
            point = target
        yaw, pitch = face_position(origin, point)
        lease.look(yaw, pitch)


class Equip(Action[int]):
    """Put an item in the held hotbar slot and select it."""

    resources = Resource.WINDOW
    name = "equip"

    def __init__(self, item: str | int, *, hotbar: int = 0) -> None:
        self.item = item
        self.hotbar = max(0, min(8, hotbar))

    def _matches(self, stack: ItemStack | None) -> bool:
        if stack is None:
            return False
        if isinstance(self.item, int):
            return stack.item_id == self.item
        name = (stack.name or "").removeprefix("minecraft:")
        return name == self.item.removeprefix("minecraft:")

    async def run(self, lease: Lease) -> int:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        for slot in range(9):
            if self._matches(host.inventory.held_item_in(slot)):
                await host.select_hotbar(slot)
                return slot
        # Move one matching main-inventory stack into the hotbar with two window clicks.
        player = host.inventory.player
        for slot in range(9, 36):
            if not self._matches(player.slot(slot)):
                continue
            target = 36 + self.hotbar
            async with lease.critical():
                await host.click_slot(slot)
                await host.click_slot(target)
            await host.select_hotbar(self.hotbar)
            return self.hotbar
        raise ActionFailed("item not in inventory", action=self.name, item=self.item)


class Eat(Action[str | None]):
    """Eat the first food stack in the hotbar."""

    resources = Resource.WINDOW | Resource.HANDS
    name = "eat"
    on_preempt = OnPreempt.ABORT

    def __init__(self, *, ticks: int = 32) -> None:
        self.ticks = max(1, ticks)

    def _find_food(self, host: ActionHost) -> tuple[int, str] | None:
        mc = _host_mc(host)
        for slot in range(9):
            stack = host.inventory.held_item_in(slot)
            if stack is None:
                continue
            name = (stack.name or "").removeprefix("minecraft:")
            food = mc.foods.get(stack.item_id)
            if food is None and name:
                food = mc.foods.get(name)
            if food is not None or name in {"golden_apple", "apple"}:
                return slot, name or f"item:{stack.item_id}"
        return None

    async def run(self, lease: Lease) -> str | None:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        found = self._find_food(host)
        if found is None:
            raise ActionFailed("no food in the hotbar", action=self.name)
        slot, name = found
        await host.select_hotbar(slot)
        async with lease.critical():
            await host.use_item()
        await host.clock.sleep(self.ticks / 20.0)
        return name


class Dig(Action[bool]):
    """Break one block with a vanilla-ish delay."""

    resources = Resource.HANDS | Resource.LOOK
    name = "dig"

    def __init__(self, pos: BlockPos, *, reach: float = 4.5) -> None:
        self.pos = pos
        self.reach = reach

    async def run(self, lease: Lease) -> bool:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        if host.position is not None:
            eye = Vec3(host.position.x, host.position.y + 1.62, host.position.z)
            if eye.distance_to(self.pos.to_vec3()) > self.reach:
                raise ActionFailed("block out of reach", action=self.name, pos=self.pos)
        try:
            state = host.world.block_at(self.pos)
        except Exception as exc:
            raise ActionFailed("block is not loaded", action=self.name, pos=self.pos) from exc
        if state.block is None or not state.block.diggable or state.block.hardness < 0:
            raise ActionFailed("block is not diggable", action=self.name, pos=self.pos)
        yaw, pitch = face_position(
            host.position or Vec3(0, 0, 0), self.pos.to_vec3()
        )
        lease.look(yaw, pitch)
        delay = (
            0.0
            if host.game_mode == 1
            else max(0.05, float(state.block.hardness) * 1.5)
        )
        async with lease.critical():
            await host.break_block(self.pos, face=Face.UP, delay=delay)
        return True


class Place(Action[bool]):
    """Place the held item against a block face."""

    resources = Resource.HANDS | Resource.LOOK
    name = "place"

    def __init__(self, pos: BlockPos, *, face: Face = Face.UP) -> None:
        self.pos = pos
        self.face = face

    async def run(self, lease: Lease) -> bool:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        if host.position is not None:
            eye = Vec3(host.position.x, host.position.y + 1.62, host.position.z)
            if eye.distance_to(self.pos.to_vec3()) > 4.5:
                raise ActionFailed("place target out of reach", action=self.name, pos=self.pos)
        yaw, pitch = face_position(
            host.position or Vec3(0, 0, 0), self.pos.to_vec3()
        )
        lease.look(yaw, pitch)
        async with lease.critical():
            await host.place_block(self.pos, face=self.face)
        return True


class Attack(Action[Entity]):
    """Attack an entity by id, or the nearest entity within ``reach``."""

    resources = Resource.LOOK | Resource.HANDS
    name = "attack"
    on_preempt = OnPreempt.ABORT

    def __init__(self, target: Entity | int | None = None, *, reach: float = 3.5) -> None:
        self.target = target
        self.reach = reach

    def _select(self, host: ActionHost) -> Entity:
        if isinstance(self.target, Entity):
            return self.target
        if isinstance(self.target, int):
            entity = host.entities.get(self.target)
            if entity is None:
                raise ActionFailed("entity is not tracked", action=self.name, target=self.target)
            return entity
        origin = host.position
        if origin is None:
            raise ActionFailed("no position", action=self.name)
        nearest: tuple[float, Entity] | None = None
        for entity in host.entities.all():
            distance = origin.distance_to(entity.position)
            if distance <= self.reach and (nearest is None or distance < nearest[0]):
                nearest = (distance, entity)
        if nearest is None:
            raise ActionFailed("no entity in reach", action=self.name)
        return nearest[1]

    async def run(self, lease: Lease) -> Entity:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        entity = self._select(host)
        origin = host.position or Vec3(0, 0, 0)
        if origin.distance_to(entity.position) > self.reach:
            raise ActionFailed("entity out of reach", action=self.name, target=entity.entity_id)
        yaw, pitch = face_position(origin, entity.position)
        lease.look(yaw, pitch)
        async with lease.critical():
            await host.swing_arm()
            await host._send_play(
                "use_entity", {"target": entity.entity_id, "mouse": 1}
            )
        return entity


class GoTo(Action[Path]):
    """Plan and walk to a goal (movement + look lease, resumable)."""

    resources = Resource.MOVEMENT | Resource.LOOK
    name = "goto"
    on_preempt = OnPreempt.RESUME
    goal: Goal

    def __init__(
        self,
        goal: Goal | BlockPos | Vec3,
        *,
        planner: PathPlanner | None = None,
        allow_partial: bool = False,
        max_nodes: int = 5000,
    ) -> None:
        resolved: Goal
        if isinstance(goal, Vec3):
            resolved = GoalBlock(goal.floored())
        elif isinstance(goal, BlockPos):
            resolved = GoalBlock(goal)
        else:
            resolved = goal
        self.goal = resolved
        self.planner = planner
        self.allow_partial = allow_partial
        self.max_nodes = max_nodes

    async def run(self, lease: Lease) -> Path:
        host: ActionHost = lease.scheduler.host  # type: ignore[assignment]
        if host.position is None:
            raise ActionFailed("cannot plan without a position", action=self.name)
        planner = self.planner or PathPlanner(
            host.world, _host_mc(host), max_nodes=self.max_nodes
        )
        path = await planner.plan(
            host.position.floored(), self.goal, allow_partial=self.allow_partial
        )
        if not path.complete and not self.allow_partial:
            raise NoPath("goal unreachable", partial=path)
        if hasattr(host, "events"):
            host.events.dispatch(
                PathStartedEvent(
                    goal=self.goal, complete=path.complete, length=len(path)
                )
            )
        executor = PathExecutor(host)
        await executor.follow(path, lease)
        return path

    async def checkpoint(self) -> object | None:
        """The goal itself is enough to resume a GoTo."""
        return self.goal

    async def restore(self, checkpoint: object | None) -> None:
        if isinstance(checkpoint, GoalBlock | GoalNear | GoalFollow):
            self.goal = checkpoint
        elif hasattr(checkpoint, "is_end"):
            self.goal = checkpoint  # type: ignore[assignment]
