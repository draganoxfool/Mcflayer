from __future__ import annotations

import asyncio

import pytest

from pyflayer._internal.clock import FakeClock, MonotonicClock


async def test_fake_clock_wakes_in_deadline_order() -> None:
    clock = FakeClock()
    order: list[str] = []

    async def sleeper(name: str, delay: float) -> None:
        await clock.sleep(delay)
        order.append(name)

    tasks = [
        asyncio.create_task(sleeper("late", 0.3)),
        asyncio.create_task(sleeper("early", 0.1)),
        asyncio.create_task(sleeper("mid", 0.2)),
    ]
    await asyncio.sleep(0)
    await clock.advance_async(0.15)
    assert order == ["early"]
    await clock.advance_async(0.1)
    assert order == ["early", "mid"]
    await clock.advance_async(0.05)
    assert order == ["early", "mid", "late"]
    await asyncio.gather(*tasks)


async def test_fake_clock_sleep_until() -> None:
    clock = FakeClock(10.0)
    task = asyncio.create_task(clock.sleep_until(10.5))
    await asyncio.sleep(0)
    clock.advance(0.25)
    assert not task.done()
    clock.advance(0.25)
    await task
    assert clock.monotonic() == 10.5


async def test_fake_clock_cancellation_removes_pending() -> None:
    clock = FakeClock()
    task = asyncio.create_task(clock.sleep(1.0))
    await asyncio.sleep(0)
    assert clock.pending == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clock.pending == 0
    clock.advance(1.0)


async def test_monotonic_clock_sleeps() -> None:
    clock = MonotonicClock()
    start = clock.monotonic()
    await clock.sleep(0.001)
    assert clock.monotonic() >= start
    await clock.sleep(-1)  # no-op


def test_fake_clock_rejects_backwards() -> None:
    with pytest.raises(ValueError):
        FakeClock().advance(-1)
