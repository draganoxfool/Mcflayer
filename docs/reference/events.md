# `pyflayer.events`

Typed, priority-ordered event bus. Events dispatch on their class, so there is no string lookup
on the hot path; handler names are derived for the `@bot.event` decorator.

```python
from pyflayer.events import EventBus, ChatEvent, SpawnEvent
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Catalog

Every event class and its corresponding handler name.

| Event | Handler (decorator) | Emitted when |
|---|---|---|
| `ConnectEvent(host, port, protocol)` | `on_connect` | TCP + login started |
| `LoginEvent(username, uuid)` | `on_login` | Login Success received |
| `JoinEvent(entity_id, game_mode, dimension, ...)` | `on_join` | Join Game received |
| `SpawnEvent(position, yaw, pitch)` | `on_spawn` | First server position |
| `RespawnEvent(dimension)` | `on_respawn` | Server respawn packet |
| `DeathEvent(health)` | `on_death` | Health reached zero |
| `HealthEvent(health, food, saturation)` | `on_health` | Health/food update |
| `ChatEvent(message: ChatMessage)` | `on_chat` | Chat/system/action-bar line |
| `PlayerInfoEvent(action, uuid, ...)` | `on_player_info` | Tab-list add/update/remove |
| `ChunkLoadEvent(pos, sections, non_air)` | `on_chunk_load` | Chunk column decoded and inserted |
| `ChunkUnloadEvent(pos)` | `on_chunk_unload` | Chunk column removed (reserved; 1.8 has no unload packet) |
| `BlockUpdateEvent(pos, state_id, old_state_id)` | `on_block_update` | Single block changed |
| `EntitySpawnEvent(entity)` | `on_entity_spawn` | Entity or player spawned |
| `EntityMoveEvent(entity, old_position=None)` | `on_entity_move` | Entity moved or received velocity |
| `EntityGoneEvent(entity)` | `on_entity_gone` | Entity removed from tracking |
| `EntityMetadataEvent(entity_id, metadata)` | `on_entity_metadata` | Entity metadata updated |
| `InventoryChangedEvent(window_id, slot, item)` | `on_inventory_changed` | Window slot changed |
| `DimensionChangeEvent(dimension, previous=None)` | `on_dimension_change` | Respawn switched dimension |
| `ExperienceEvent(bar, level, total)` | `on_experience` | Experience bar/level updated |
| `KickEvent(reason, reason_text)` | `on_kick` | Server kick |
| `DisconnectEvent(reason, error)` | `on_disconnect` | Connection ended |
| `ErrorEvent(event, listener, exception)` | `on_error` | A listener raised |
| `PhysicsTickEvent(tick, position, on_ground)` | `on_physics_tick` | One bot physics tick completed |

## Bus API

```python
from pyflayer.events import EventBus, ChatEvent

bus = EventBus()

# Subscribe a handler
sub = bus.subscribe(ChatEvent, handler, priority=0, once=False, owner=None)

# Unsubscribe
bus.unsubscribe(sub)
bus.unsubscribe_owner(owner=cog)

# Dispatch (synchronous, never raises into caller)
bus.dispatch(ChatEvent(message=msg))

# Wait for a specific event
event = await bus.wait_for(ChatEvent, check=lambda e: e.message.sender == "Steve", timeout=5)

# Expect: register a waiter, then await
waiter = bus.expect(RespawnEvent, timeout=5)

# Stream events with bounded queue
async for event in bus.stream(ChatEvent, maxsize=256):
    ...

# Close the bus
await bus.aclose()
```

## Semantics

- `dispatch` is synchronous and never raises into the caller. Delivery order is: listeners with
  `priority >= 1000` (the bot's internal state hooks), then `wait_for`/`expect` waiters, then
  ordinary listeners.
- Internal hooks run inline so state is updated before user code sees the event (ADR-4). Ordinary
  synchronous listeners are called inline; awaitable results are scheduled as tracked tasks, so a
  slow async handler cannot block the bus. An async internal hook is scheduled rather than awaited.
- A listener exception becomes `ErrorEvent` (and is logged when nothing listens for errors).
- `expect()` registers its waiter synchronously on `__aenter__`, so an event dispatched immediately
  after entering the context cannot be missed.
- `stream()` uses a bounded queue: on overflow the oldest event is dropped and `dropped` increments.
  Breaking out of an `async for` does **not** close the stream automatically; call
  `stream.aclose()` or use `contextlib.aclosing()`.
- `aclose()` cancels tracked listener tasks and clears subscriptions. It also marks the bus closed;
  close streams explicitly if you created any.
- Timeouts use the injected `Clock`, so they are deterministic under `FakeClock`.

## Quick example

```python
import asyncio
import pyflayer

bot = pyflayer.Bot("Steve", host="play.pika-network.net")

@bot.event
async def on_chat(event):
    print(f"[{event.message.sender}] {event.message.content}")

@bot.event
async def on_spawn(event):
    print(f"Spawned at {event.position}")

await bot.connect()
await bot.run()
```