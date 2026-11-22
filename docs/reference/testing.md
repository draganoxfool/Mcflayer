# `pyflayer.testing`

Testing helpers exported by `pyflayer.testing`. `FakeClock` is in
[`pyflayer._internal`](internal.md), not in this package.

::: pyflayer.testing
    options:
      members: [FakeServer]
      show_root_heading: false
    show_root_toc_entry: false

<!--

Testing utilities: `FakeServer` for offline integration tests and `FakeClock` for deterministic
time control.

```python
from pyflayer.testing import FakeServer
from pyflayer._internal.clock import FakeClock
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## FakeClock

A deterministic `Clock` for tests. Sleepers are woken in deadline order; `advance_async()` also
lets the awakened tasks run.

```python
from pyflayer._internal.clock import FakeClock

clock = FakeClock()
task = asyncio.create_task(clock.sleep(0.5))
await asyncio.sleep(0)
clock.advance(0.5)
await task
print(clock.monotonic())  # 0.5
print(clock.pending)  # 0
```

| Method / property | Meaning |
|---|---|
| `monotonic()` | Current deterministic time |
| `sleep(seconds)` | Sleep on this clock |
| `sleep_until(deadline)` | Sleep until an absolute deadline |
| `advance(seconds)` | Move time forward and wake due sleepers |
| `advance_async(seconds)` | Advance, then yield so awakened tasks run |
| `pending` | Number of sleepers not yet woken |

## FakeServer

An in-process 1.8.9 server emulator. It implements handshake/login, optional RSA/AES encryption,
optional compression, Join Game, keep-alive echo, chat echo and respawn — enough to test the bot
without Docker or a real server.

```python
from pyflayer.testing import FakeServer

server = FakeServer(compression=64, encryption=True)
await server.start()
print(server.port)
...
await server.stop()
```

It is also an async context manager:

```python
async with FakeServer() as server:
    ...
```

**Arguments**

| Argument | Meaning |
|---|---|
| `version` | Data version to serve (default `"1.8.9"`) |
| `compression` | Compression threshold, or `-1` to leave compression off |
| `encryption` | Require the RSA/AES handshake |
| `kick_after_join` | Send a kick immediately after Join Game |
| `kick_reason` | JSON chat component used for that kick |
| `reject_login` | JSON chat component used to reject Login Start |
| `join_delay` | Seconds to wait before Join Game |
| `host`, `port` | Bind address; port `0` chooses a free port |

**Attributes / methods**

| Member | Meaning |
|---|---|
| `start()` | Start listening and return `self` |
| `stop()` | Stop listening and close every connection |
| `port` | Bound port (available after `start()`) |
| `received` | Packets received from clients |
| `chats` | Chat lines received |
| `usernames` | Names seen in Login Start |
| `settings` | Last client settings packet, if any |
| `keep_alives` | Keep-alive ids received |
| `send_play(name, fields)` | Send a Play packet to every live connection |
| `announce(text)` | Send a server chat line |
| `encode(...)`, `decode(...)` | Use the server's registry directly |

`FakeServer` does **not** create or connect a `Bot` for you; construct one with the server's port:

```python
bot = Bot("Steve", host="127.0.0.1", port=server.port, use_srv=False)
```

## Quick example — bot chat round trip

```python
import asyncio

from pyflayer import Bot
from pyflayer.events import ChatEvent
from pyflayer.testing import FakeServer


async def main() -> None:
    async with FakeServer() as server:
        bot = Bot("Steve", host="127.0.0.1", port=server.port, use_srv=False)
        await bot.connect()

        received: list[ChatEvent] = []
        bot.events.subscribe(ChatEvent, received.append)
        task = asyncio.create_task(bot.run())
        await bot.chat("hello")
        async with asyncio.timeout(2):
            while not received:
                await asyncio.sleep(0.01)

        print(received[0].message.content)  # <Steve> hello
        await bot.close()
        await task


asyncio.run(main())
```

## Quick example — deterministic physics

```python
import asyncio

from pyflayer._internal.clock import FakeClock
from pyflayer.data import McData
from pyflayer.models import Vec3
from pyflayer.physics import ControlState, PhysicsEngine, PlayerState, TickDriver
from pyflayer.world import World

mc = McData.load("1.8.9")
world = World(mc)
engine = PhysicsEngine()
clock = FakeClock()
state = PlayerState(Vec3(0.0, 64.0, 0.0), on_ground=True)


async def tick(tick_number: int) -> None:
    global state
    state = engine.step(state, ControlState(forward=1.0), world)


async def main() -> None:
    driver = TickDriver(clock)
    task = asyncio.create_task(driver.run(tick))
    await asyncio.sleep(0)
    for _ in range(20):
        await clock.advance_async(1 / 20)
    driver.stop()
    await task


asyncio.run(main())
```
