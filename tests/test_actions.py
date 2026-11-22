from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.actions import (
    Action,
    ActionState,
    Dig,
    Equip,
    GoTo,
    Look,
    Priority,
    Resource,
    SurvivalMonitor,
)
from pyflayer.actions.base import OnPreempt
from pyflayer.actions.basic import face_position
from pyflayer.bot.inventory import Inventory
from pyflayer.data import McData
from pyflayer.errors import ActionBusy, ActionCancelled, ActionFailed, ActionPreempted
from pyflayer.events.bus import EventBus
from pyflayer.events.catalog import HealthEvent, PhysicsTickEvent
from pyflayer.models.items import ItemStack
from pyflayer.models.vec3 import BlockPos, ChunkPos, Vec3
from pyflayer.world.block import BlockState
from pyflayer.world.entities import EntityTracker

MC = McData.load("1.8.9")
STONE = 16


class FlatWorld:
    min_y = 0
    height = 256
    mc = MC

    def is_loaded(self, pos: ChunkPos) -> bool:
        return True

    def block_state_id(self, pos: BlockPos) -> int:
        return STONE if pos.y < 64 else 0

    def block_at(self, pos: BlockPos) -> BlockState:
        return BlockState.from_legacy(self.block_state_id(pos), MC)

    def snapshot(self) -> FlatWorld:
        return self


class FakeEvents:
    def __init__(self, host: Host) -> None:
        self.host = host
        self.dispatched: list[object] = []

    def dispatch(self, event: object) -> None:
        self.dispatched.append(event)

    async def wait_for(
        self,
        event: type,
        timeout: float | None = None,  # noqa: ASYNC109 - mirrors the bot API
    ) -> object:
        del timeout
        self.host.step()
        return PhysicsTickEvent(0, self.host.position or Vec3(0, 0, 0), True)


class Hold(Action[str]):
    resources = Resource.MOVEMENT

    def __init__(self, name: str = "hold") -> None:
        self.name = name
        self.release = asyncio.Event()
        self.runs = 0

    async def run(self, lease: Any) -> str:
        self.runs += 1
        lease.controls.set(forward=1.0)
        await self.release.wait()
        return self.name


class Resume(Action[str]):
    resources = Resource.MOVEMENT
    name = "resume"
    on_preempt = OnPreempt.RESUME

    def __init__(self) -> None:
        self.runs = 0
        self.block = asyncio.Event()

    async def run(self, lease: Any) -> str:
        self.runs += 1
        if self.runs == 1:
            lease.controls.set(forward=1.0)
            await self.block.wait()
        return "resumed"


class Instant(Action[str]):
    resources = Resource.MOVEMENT

    def __init__(self) -> None:
        self.name = "instant"

    async def run(self, lease: Any) -> str:
        del lease
        return "done"


class Host:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.events = FakeEvents(self)
        self.world = FlatWorld()
        self.position = Vec3(0.5, 64.0, 0.5)
        self.game_mode = 1
        self.entities = EntityTracker(MC)
        self.inventory = Inventory()
        self.movement = (0.0, 0.0)
        self.yaw = 0.0
        self.pitch = 0.0
        self.jumps = 0
        self.broke: list[BlockPos] = []
        self.placed: list[BlockPos] = []
        self.used = 0
        self.held = 0
        from pyflayer.actions.scheduler import ActionScheduler

        self.scheduler = ActionScheduler(self, clock=self.clock)

    def set_movement(
        self,
        forward: float = 0.0,
        strafe: float = 0.0,
        *,
        sprint: bool = False,
        sneak: bool = False,
    ) -> None:
        del sprint, sneak
        self.movement = (forward, strafe)

    def stop_movement(self) -> None:
        self.movement = (0.0, 0.0)

    def look(self, *, yaw: float | None = None, pitch: float | None = None) -> None:
        self.yaw = self.yaw if yaw is None else yaw
        self.pitch = self.pitch if pitch is None else pitch

    def jump(self) -> None:
        self.jumps += 1

    async def select_hotbar(self, slot: int) -> None:
        self.held = slot

    async def click_slot(self, slot: int, **kwargs: Any) -> int:
        del slot, kwargs
        return 1

    async def break_block(self, pos: BlockPos, **kwargs: Any) -> None:
        del kwargs
        self.broke.append(pos)

    async def place_block(self, pos: BlockPos, **kwargs: Any) -> None:
        del kwargs
        self.placed.append(pos)

    async def use_item(self) -> None:
        self.used += 1

    async def swing_arm(self) -> None:
        return None

    async def _send_play(self, name: str, fields: dict[str, object]) -> None:
        del name, fields

    def step(self) -> None:
        forward, _strafe = self.movement
        if forward <= 0 or self.position is None:
            return
        radians = math.radians(self.yaw)
        self.position = Vec3(
            self.position.x - math.sin(radians) * 0.3,
            self.position.y,
            self.position.z + math.cos(radians) * 0.3,
        )


async def settle(times: int = 5) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def running(handle: Any) -> None:
    for _ in range(100):
        if handle.state is ActionState.RUNNING:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"handle never started: {handle!r}")


def test_face_position_points_at_the_target() -> None:
    yaw, pitch = face_position(Vec3(0, 0, 0), Vec3(0, 0, 1))
    assert yaw == pytest.approx(0.0)
    assert pitch == pytest.approx(0.0)
    yaw, _pitch = face_position(Vec3(0, 0, 0), Vec3(1, 0, 0))
    assert yaw == pytest.approx(-90.0)


async def test_look_writes_the_leases_controls() -> None:
    host = Host()
    await host.scheduler.run(Look(45.0, 10.0))
    assert host.yaw == 45.0
    assert host.pitch == 10.0


async def test_busy_resources_raise_without_queueing() -> None:
    host = Host()
    first = Hold()
    handle = host.scheduler.run(first)
    await running(handle)

    with pytest.raises(ActionBusy):
        await host.scheduler.run(Instant())

    first.release.set()
    assert await handle == "hold"


async def test_higher_priority_preempts_and_aborts() -> None:
    host = Host()
    low = Hold()
    low_handle = host.scheduler.run(low, priority=Priority.WORK)
    await running(low_handle)

    high_handle = host.scheduler.run(Instant(), priority=Priority.USER)
    assert await high_handle == "done"

    with pytest.raises(ActionPreempted):
        await low_handle
    assert host.movement == (0.0, 0.0)


async def test_resume_action_reruns_after_preemption() -> None:
    host = Host()
    action = Resume()
    handle = host.scheduler.run(action, priority=Priority.WORK)
    await running(handle)

    assert await host.scheduler.run(Instant(), priority=Priority.USER) == "done"
    assert await handle == "resumed"
    assert action.runs == 2


async def test_queue_waits_for_the_holder() -> None:
    host = Host()
    first = Hold()
    holder = host.scheduler.run(first)
    await running(holder)

    queued = host.scheduler.run(Instant(), priority=Priority.SURVIVAL, queue=True)
    await settle()
    assert not queued.done

    first.release.set()
    assert await queued == "done"


async def test_timeout_fails_the_action() -> None:
    host = Host()
    handle = host.scheduler.run(Hold(), timeout=2.0)
    await running(handle)
    await settle()

    await host.clock.advance_async(2.0)
    with pytest.raises(ActionFailed, match="timed out"):
        await handle
    assert handle.state is ActionState.CANCELLED


async def test_death_barrier_and_cancel_all() -> None:
    host = Host()
    first = Hold()
    handle = host.scheduler.run(first)
    await running(handle)

    host.scheduler.set_barrier(True)
    with pytest.raises(ActionCancelled):
        await handle

    blocked = host.scheduler.run(Instant())
    await settle()
    assert not blocked.done

    host.scheduler.release_barrier()
    assert await blocked == "done"


async def test_inherited_child_does_not_reacquire_resources() -> None:
    class Child(Action[str]):
        resources = Resource.MOVEMENT
        name = "child"

        async def run(self, lease: Any) -> str:
            lease.controls.set(forward=0.5)
            return "child"

    class Parent(Action[str]):
        resources = Resource.MOVEMENT | Resource.LOOK
        name = "parent"

        async def run(self, lease: Any) -> str:
            return await lease.child(Child())

    host = Host()
    assert await host.scheduler.run(Parent()) == "child"
    assert host.scheduler.idle


async def test_equip_selects_a_hotbar_stack() -> None:
    host = Host()
    host.inventory.player.items[36] = ItemStack(
        item_id=1, name="minecraft:stone_sword", count=1
    )
    slot = await host.scheduler.run(Equip("stone_sword"))
    assert slot == 0
    assert host.held == 0


async def test_dig_breaks_the_target_in_creative() -> None:
    host = Host()
    target = BlockPos(1, 63, 0)
    assert await host.scheduler.run(Dig(target, reach=10.0))
    assert host.broke == [target]


async def test_goto_plans_and_walks_to_the_goal() -> None:
    host = Host()
    goal = BlockPos(2, 64, 0)
    path = await host.scheduler.run(GoTo(goal))
    assert path.end == goal
    assert host.position is not None and host.position.x >= 2.0
    assert host.movement == (0.0, 0.0)
    assert host.scheduler.idle


class FakeTask:
    def add_done_callback(self, callback: Any) -> None:
        del callback


class RecordingScheduler:
    def __init__(self) -> None:
        self.submitted: list[Action[Any]] = []

    def current(self) -> None:
        return None

    def run(self, action: Action[Any], *, priority: Priority) -> Any:
        del priority
        self.submitted.append(action)
        return type("Handle", (), {"task": FakeTask()})()


class MonitorHost:
    def __init__(self) -> None:
        self.events = EventBus()
        self.scheduler = RecordingScheduler()


def test_survival_monitor_eats_when_health_is_low() -> None:
    host = MonitorHost()
    monitor = SurvivalMonitor(host)
    monitor.start()

    host.events.dispatch(HealthEvent(health=20.0, food=20, saturation=5.0))
    assert host.scheduler.submitted == []

    host.events.dispatch(HealthEvent(health=4.0, food=10, saturation=0.0))
    assert len(host.scheduler.submitted) == 1
    assert host.scheduler.submitted[0].name == "eat"
    assert monitor.health == 4.0


def test_survival_monitor_can_be_disabled() -> None:
    host = MonitorHost()
    monitor = SurvivalMonitor(host)
    monitor.start()
    monitor.enabled = False
    host.events.dispatch(HealthEvent(health=1.0, food=10, saturation=0.0))
    assert host.scheduler.submitted == []
