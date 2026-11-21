# `pyflayer`

```python
import pyflayer
```

The top-level package is a convenience surface: it re-exports the classes you need for the common
tasks (connect, read events, inspect the world, drive a physics tick) so a bot can be written with a
single import. The defining modules remain importable and are the canonical paths; this page
documents the constants and entry points that live only here.

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members:
        - __version__
        - PROTOCOL_VERSION
        - REFERENCE_VERSION
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Server list ping

`ping()` and `ServerStatus` answer "is the server up, what version, who is online" without logging
in. They are loaded lazily, which keeps `import pyflayer` fast.

::: pyflayer.protocol.status.ServerStatus
    options:
      members: false
      show_root_heading: true

::: pyflayer.protocol.status.ping

```python
import asyncio

import pyflayer

status = asyncio.run(pyflayer.ping("play.pika-network.net"))
print(status.version_name, status.online_players, status.latency_ms)
```

## Re-exports

Everything in this table is also available as `pyflayer.<Name>`; follow the link for the full
contract.

| Name | Defining module |
|---|---|
| `Bot`, `BotState`, `PlayerInfo` | [`pyflayer.bot`](bot.md) |
| `ChatEvent`, `SpawnEvent`, `JoinEvent`, `EventBus` | [`pyflayer.events`](events.md) |
| `Connection`, `ConnectionState`, `FrameCodec`, `StateMachine` | [`pyflayer.protocol`](protocol.md) |
| `Packet`, `PacketReader`, `PacketWriter`, `PacketRegistry` | [`pyflayer.protocol`](protocol.md) |
| `ProtocolClient` | [`pyflayer.protocol.client`](protocol.md#protocolclient) |
| `McData`, `Features`, `VersionInfo` | [`pyflayer.data`](data.md) |
| `BlockState`, `ChunkColumn`, `ChunkSection`, `Entity`, `EntityTracker` | [`pyflayer.world`](world.md) |
| `World`, `WorldSnapshot`, `PalettedContainer`, `RayHit` | [`pyflayer.world`](world.md) |
| `PhysicsEngine`, `PlayerState`, `ControlState`, `TickDriver` | [`pyflayer.physics`](physics.md) |
| `Vec3`, `BlockPos`, `ChunkPos`, `SectionPos`, `AABB` | [`pyflayer.models`](models.md) |
| `ChatComponent`, `ChatMessage`, `ItemStack` | [`pyflayer.models`](models.md) |
| `Dimension`, `GameMode` | [`pyflayer.models`](models.md) |
| `PyFlayerError`, `errors` | [`pyflayer.errors`](errors.md) |

## Quick example

```python
import asyncio

import pyflayer
from pyflayer.events import ChatEvent, SpawnEvent


async def main() -> None:
    bot = pyflayer.Bot("Steve", host="play.pika-network.net")

    @bot.event
    async def on_spawn(event: SpawnEvent) -> None:
        print("spawned at", event.position)

    @bot.event
    async def on_chat(event: ChatEvent) -> None:
        print(event.message.content)

    await bot.connect()
    await bot.chat("hello")
    await bot.run()


asyncio.run(main())
```

See the [Quickstart](../quickstart.md) for a runnable version and the
[Bot reference](bot.md) for every method.
