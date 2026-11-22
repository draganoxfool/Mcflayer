# Events

`pyflayer.events` provides frozen event records and a typed event bus. `@bot.event` resolves handler
names such as `on_chat` to catalog event classes.

## Catalog

| Event | Handler | Emitted when |
|---|---|---|
| `ConnectEvent(host, port, protocol)` | `on_connect` | TCP + login started |
| `LoginEvent(username, uuid)` | `on_login` | Login Success received |
| `JoinEvent(entity_id, game_mode, dimension, …)` | `on_join` | Join Game received |
| `SpawnEvent(position, yaw, pitch)` | `on_spawn` | First server position |
| `RespawnEvent(dimension)` | `on_respawn` | Server respawn packet |
| `DeathEvent(health)` | `on_death` | Health reached zero |
| `HealthEvent(health, food, saturation)` | `on_health` | Health/food update |
| `ChatEvent(message: ChatMessage)` | `on_chat` | Chat/system/action-bar line |
| `PlayerInfoEvent(action, uuid, …)` | `on_player_info` | Tab-list add/update/remove |
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
| `ActionStartedEvent(action, priority, resources)` | `on_action_started` | An action acquired its lease and started |
| `ActionFinishedEvent(action, state, duration, error=None)` | `on_action_finished` | An action reached a terminal state |
| `ActionPreemptedEvent(action, by=None)` | `on_action_preempted` | A higher-priority action took the lease |
| `PathStartedEvent(goal, complete, length)` | `on_path_started` | A plan is ready and following starts |
| `PathUpdatedEvent(position, waypoint)` | `on_path_updated` | The executor reached a waypoint |
| `PathResetEvent(reason)` | `on_path_reset` | A path was abandoned |
| `GoalReachedEvent(goal)` | `on_goal_reached` | The final waypoint was reached |

## Bus API

```python
bus = EventBus()
sub = bus.subscribe(ChatEvent, handler, priority=0, once=False, owner=cog)
bus.unsubscribe(sub)
bus.unsubscribe_owner(cog)
bus.dispatch(ChatEvent(message=msg))

event = await bus.wait_for(ChatEvent, check=lambda e: e.message.sender == "Steve", timeout=5)
async with bus.expect(RespawnEvent, timeout=5) as expected:
  await perform_respawn()
event = await expected
async with bus.stream(ChatEvent, maxsize=256) as events:
    async for event in events:
        ...
await bus.aclose()
```

The stream remains an async iterator and supports explicit `await stream.aclose()`. Use the async
context manager when iteration may stop early; `async for` alone does not unsubscribe on `break`.

## Semantics

- `dispatch` is synchronous and does not propagate listener exceptions. Delivery order is internal
  listeners with `priority >= 1000`, waiters, then ordinary listeners.
- Internal hooks run inline so state is updated before user code sees the event (ADR-4). Ordinary
  synchronous listeners are called inline; awaitable results are scheduled as tracked tasks, so a
  slow async handler cannot block the bus. An async internal hook is scheduled rather than awaited.
- A listener exception becomes `ErrorEvent` (and is logged when nothing listens for errors).
- `expect()` returns an awaitable context manager. Its waiter is registered on `__aenter__`; enter
  the context before starting the operation that may dispatch the event. Await the context value
  before leaving the context.
- `stream()` uses a bounded queue: on overflow the oldest event is dropped and `dropped` increments.
  Breaking out of an `async for` does **not** close the stream automatically; call
  `stream.aclose()` or use `contextlib.aclosing()`.
- `aclose()` cancels tracked listener tasks, clears subscriptions and waiters, and marks the bus
  closed. Close streams explicitly if they were created outside a context manager.
- Timeouts use the injected `Clock`, so they are deterministic under `FakeClock`.
