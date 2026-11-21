from __future__ import annotations

import asyncio

import pytest

from pyflayer._internal.clock import FakeClock
from pyflayer.events import (
    ChatEvent,
    DeathEvent,
    ErrorEvent,
    EventBus,
    HealthEvent,
    event_for_name,
)
from pyflayer.models.chat import ChatMessage


def _chat(text: str = "hi") -> ChatEvent:
    return ChatEvent(message=ChatMessage(content=text))


def test_event_names_and_catalog() -> None:
    assert ChatEvent.__event_name__ == "on_chat"
    assert HealthEvent.__event_name__ == "on_health"
    assert event_for_name("on_chat") is ChatEvent
    with pytest.raises(KeyError):
        event_for_name("on_nope")


async def test_sync_and_async_listeners() -> None:
    bus = EventBus()
    seen: list[str] = []

    def sync_listener(event: ChatEvent) -> None:
        seen.append("sync:" + event.message.content)

    async def async_listener(event: ChatEvent) -> None:
        await asyncio.sleep(0)
        seen.append("async:" + event.message.content)

    bus.subscribe(ChatEvent, sync_listener)
    bus.subscribe(ChatEvent, async_listener)
    bus.dispatch(_chat())
    assert seen == ["sync:hi"]
    await asyncio.sleep(0.01)
    assert seen == ["sync:hi", "async:hi"]
    await bus.aclose()


async def test_priority_order_with_inline_internal_hooks() -> None:
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(ChatEvent, lambda event: order.append("user"), priority=0)

    def hook(event: ChatEvent) -> None:
        order.append("hook")

    bus.subscribe(ChatEvent, hook, priority=1000)
    bus.dispatch(_chat())
    # Internal state hooks run inline before user listeners (ADR-4).
    assert order == ["hook", "user"]
    await bus.aclose()


async def test_internal_hook_runs_before_waiters() -> None:
    bus = EventBus()
    order: list[str] = []

    def hook(event: ChatEvent) -> None:
        order.append("hook")

    bus.subscribe(ChatEvent, hook, priority=1000)
    waiter = asyncio.create_task(bus.wait_for(ChatEvent, timeout=1))
    await asyncio.sleep(0)
    bus.dispatch(_chat())
    assert order == ["hook"]
    await waiter
    assert order == ["hook"]
    await bus.aclose()


async def test_once_and_owner_unsubscribe() -> None:
    bus = EventBus()
    owner = object()
    calls: list[str] = []
    bus.subscribe(ChatEvent, lambda event: calls.append("once"), once=True, owner=owner)
    bus.subscribe(ChatEvent, lambda event: calls.append("always"), owner=owner)
    bus.dispatch(_chat("a"))
    await asyncio.sleep(0)
    assert calls == ["once", "always"]
    assert bus.subscription_count == 1
    assert bus.unsubscribe_owner(owner) == 1
    assert bus.subscription_count == 0
    bus.dispatch(_chat("b"))
    await asyncio.sleep(0)
    assert calls == ["once", "always"]


async def test_wait_for_resolves_and_check_filters() -> None:
    bus = EventBus()
    task = asyncio.create_task(
        bus.wait_for(ChatEvent, check=lambda event: event.message.content == "target", timeout=5)
    )
    await asyncio.sleep(0)
    bus.dispatch(_chat("other"))
    await asyncio.sleep(0)
    assert not task.done()
    bus.dispatch(_chat("target"))
    event = await task
    assert event.message.content == "target"


async def test_wait_for_timeout_uses_clock() -> None:
    clock = FakeClock()
    bus = EventBus(clock=clock)
    task = asyncio.create_task(bus.wait_for(ChatEvent, timeout=1.0))
    await asyncio.sleep(0)
    await clock.advance_async(1.0)
    with pytest.raises(TimeoutError):
        await task
    assert bus.task_count == 0


async def test_expect_cannot_miss_an_event() -> None:
    bus = EventBus()

    async def action() -> None:
        bus.dispatch(_chat("during"))

    async with bus.expect(ChatEvent, timeout=1) as expectation:
        await action()
    event = await expectation
    assert event.message.content == "during"


async def test_expect_survives_cancellation_in_context() -> None:
    bus = EventBus()
    expectation = bus.expect(ChatEvent)
    with pytest.raises(ValueError):
        async with expectation:
            raise ValueError("boom")
    await asyncio.sleep(0)


async def test_listener_error_becomes_error_event() -> None:
    bus = EventBus()
    errors: list[ErrorEvent] = []

    def broken(event: ChatEvent) -> None:
        raise RuntimeError("nope")

    bus.subscribe(ChatEvent, broken)
    bus.subscribe(ErrorEvent, errors.append)
    bus.dispatch(_chat())
    await asyncio.sleep(0)
    assert len(errors) == 1
    assert isinstance(errors[0].exception, RuntimeError)


async def test_stream_and_overflow() -> None:
    bus = EventBus()
    stream = bus.stream(ChatEvent, maxsize=2)
    first_task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    bus.dispatch(_chat("first"))
    first = await first_task
    assert first.message.content == "first"
    bus.dispatch(_chat("a"))
    bus.dispatch(_chat("b"))
    bus.dispatch(_chat("c"))
    got = [await stream.__anext__(), await stream.__anext__()]
    assert [event.message.content for event in got] == ["b", "c"]
    assert stream.dropped == 1
    await stream.aclose()


async def test_aclose_cancels_listener_tasks() -> None:
    bus = EventBus()
    started = asyncio.Event()

    async def slow(event: DeathEvent) -> None:
        started.set()
        await asyncio.sleep(60)

    bus.subscribe(DeathEvent, slow)
    bus.dispatch(DeathEvent(health=0))
    await started.wait()
    assert bus.task_count == 1
    await bus.aclose()
    assert bus.task_count == 0
    assert bus.subscription_count == 0
