# Bot

`pyflayer.bot.Bot` is the composition root: a `ProtocolClient` plus an `EventBus`, with player,
world, entity, inventory and physics state. Since M4 the bot owns a 20 TPS tick loop, simulates the
player with [`PhysicsEngine`](physics.md), emits vanilla-style movement packets and confirms server
teleports. The action scheduler arrives in a later milestone.

## Quick start

```python
import pyflayer
from pyflayer.events import ChatEvent, SpawnEvent

bot = pyflayer.Bot("Steve", host="play.pika-network.net")


@bot.event
async def on_chat(event: ChatEvent):
    print(event.message)


@bot.event
async def on_spawn(event: SpawnEvent):
    print("spawned at", event.position)


join = await bot.connect()  # returns JoinEvent; sends client settings
await bot.chat("hello")
await bot.run()  # read packets until disconnected
```

`connect()` returns as soon as Join Game has been handled. The initial position, tab-list entries
and other play packets arrive afterwards while `run()` is reading; await `SpawnEvent` (or
`wait_until_ready()` plus a spawn check) before relying on `bot.position` or `bot.players`.

CLI equivalent:

```bash
pyflayer-connect play.pika-network.net --username Steve --timeout 15 --chat "hello"
python -m pyflayer.cli play.pika-network.net -u Steve --timeout 15
```

## What the bot handles

| Packet | Behaviour |
|---|---|
| `login` (Join Game) | entity id, dimension, game mode, settings, `JoinEvent` |
| `keep_alive` | echoes the id immediately |
| `position` | reconciles position/yaw/pitch, seeds `physics_state`, first one emits `SpawnEvent` and starts the tick loop; later ones schedule a teleport confirmation |
| `chat` | parses 1.8 JSON (unwrap `chat.type.text`, whisper/action-bar), `ChatEvent` |
| `update_health` | health/food/saturation, `HealthEvent`, `DeathEvent` + auto respawn |
| `respawn` | clears `dead`, `RespawnEvent` |
| `kick_disconnect` | parses the reason, `KickEvent`, raises `KickedError` from `run()` |
| `player_info` | `players` keyed by UUID, `PlayerInfoEvent` |
| `game_state_change` | updates game mode |
| `map_chunk`, `map_chunk_bulk` | decodes chunks into `bot.world`; partial chunks merge into the existing column; `ChunkLoadEvent` |
| `block_change`, `multi_block_change` | updates `bot.world`; `BlockUpdateEvent` |
| entity spawn/move/look/teleport/velocity/attach | updates `bot.entities`; `EntitySpawnEvent`, `EntityMoveEvent`, `EntityGoneEvent`, `EntityMetadataEvent` |
| `window_items`, `set_slot`, `held_item_slot`, `open_window`, `close_window` | updates `bot.inventory`; `InventoryChangedEvent` |
| `experience` | bar, level and total; `ExperienceEvent` |
| `update_attributes` | movement/combat attributes in `bot.attributes` |
| everything else | debug log |

## State and helpers

`bot.state` is an immutable `BotState` snapshot. Also exposed: `username`, `uuid`, `entity_id`,
`position`, `spawn_position`, `yaw`, `pitch`, `health`, `food`, `saturation`, `game_mode`,
`dimension`, `dead`, `players`, `world`, `entities`, `inventory`, `experience`, `attributes`,
`physics`, `physics_state`, `controls`, `movement` and `tick_driver`.

- `bot.find_blocks(name, within=32, count=1)` delegates to `World.find_blocks` around the bot.
- `bot.world.raycast(origin, direction, max_dist)` and `World.snapshot(...)` expose read-only views.
- `await bot.respawn()` sends `client_command(perform_respawn)`.
- `await bot.send_command("/register pw pw")` adds the slash if absent.
- `await bot.wait_until_ready()` resolves after Join Game.
- `await bot.wait_for(...)` / `bot.expect(...)` delegate to the event bus.
- `Bot(..., reconnect=True)` reconnects with exponential backoff (1 s → `max_backoff`); a kick stops
  the loop and raises `KickedError`.

See the [World module](world.md) for chunk, entity and inventory semantics.

## New API modules

The action primitives were split into focused modules since M5:

| Module | Key functions |
|---|---|
| `pyflayer.bot.windows` | Window packet operations: `select_hotbar()`, `click_slot()`, `shift_click_slot()`, `drop_slot()`, `close_window()` |
| `pyflayer.bot.interactions` | Block/item packet primitives: `swing_arm()`, `use_item()`, `place_block()`, `start_digging()`, `finish_digging()`, `cancel_digging()`, `break_block()` |

Both modules are thin delegates off `Bot`; the `Bot` methods themselves have been refactored to delegate to them.

- `bot.select_hotbar(slot)` selects a hotbar slot
- `bot.click_slot(window, slot, mode=ClickMode.LEFT, action=...)` sends a window click
- `bot.use_item()` uses the block_place sentinel (cursor at -1,-1,-1, dir -1)
- `bot.place_block(pos, face)` places a block at the given position and direction
- `bot.start_digging(pos, face)` starts digging a block
- `bot.break_block(pos, face, delay=...)` breaks a block with optional delay

## Movement and physics

The bot creates one `TickDriver` when the first server position arrives. It steps the engine 20
times per second, updates `position`/`yaw`/`pitch`, sends movement, and dispatches a
`PhysicsTickEvent` after every tick. The loop stops on `close()`, respawn resets the pose, and no
simulation runs while the bot is dead or its current chunk is not loaded.

### Controls

Controls are written from any coroutine and consumed by the next tick. They are **not** awaited;
the tick loop samples the latest value.

| Method / property | Effect |
|---|---|
| `bot.set_movement(forward, strafe, *, sprint=False, sneak=False)` | Continuous input. `forward` is positive towards the facing direction, `strafe` positive to the left. |
| `bot.stop_movement()` | Clears input and a pending jump, keeping the look direction. |
| `bot.look(*, yaw=None, pitch=None)` | Sets the look direction (degrees). Omitted values are unchanged. |
| `bot.jump()` | Requests **one** jump on the next tick. Ignored unless the player can jump. |
| `bot.on_ground` | Whether the last completed tick ended on a support. |
| `bot.teleport_confirm_supported` | `True` when the protocol has teleport ids (1.9+). |
| `bot.physics_state` | The latest `PlayerState` (`None` before spawn/reset). |

```python
import asyncio

from pyflayer.events import SpawnEvent

await bot.connect()
task = asyncio.create_task(bot.run())  # run() owns packet reading
await bot.wait_for(SpawnEvent)

bot.look(yaw=270.0)  # face +X
bot.set_movement(forward=1.0, sprint=True)
await asyncio.sleep(1.0)  # about 20 physics ticks
bot.jump()  # one tick only
bot.stop_movement()

await bot.close()
await asyncio.gather(task, return_exceptions=True)
```

!!! note "World coverage"
    Physics pauses when `bot.world.is_loaded(current_chunk)` is false. Keep the chunk under the
    player loaded, or the bot will intentionally stand still rather than fall through unloaded
    terrain.

### Packet cadence

`MovementTracker` implements the 1.8 client rules and is pure, so the cadence is tested without a
socket. It sends at most **one movement packet per tick**:

1. A position packet when the squared distance from the last sent position exceeds **`4e-8`**, or
   every **20 ticks** as a reminder.
2. A rotation packet when yaw or pitch changes by more than `1e-5` degrees.
3. A ground-state packet when `on_ground` flips.

| Change | Packet | Fields |
|---|---|---|
| Position and/or reminder, rotation unchanged | `position` | `x`, `y`, `z`, `onGround` |
| Position and/or reminder **and** rotation | `position_look` | `x`, `y`, `z`, `yaw`, `pitch`, `onGround` |
| Rotation only | `look` | `yaw`, `pitch`, `onGround` |
| Ground flag only | `flying` | `onGround` |

When the bot starts sprinting or sneaking, it first sends `entity_action` with `start_sprinting`,
`stop_sprinting`, `start_sneaking` or `stop_sneaking`. Servers validate movement against the state
they were told about, so this ordering avoids false setbacks.

### Teleport reconciliation

A server `position` packet is authoritative. The bot applies relative flags, rebuilds
`physics_state`, resets the movement baseline and schedules a confirmation for the next tick:

- **1.9+** — sends `teleport_confirm` with the server's `teleportId`.
- **1.8** — has no teleport id; the client confirms by echoing its pose with `position_look`, which
  is why `teleport_confirm_supported` is feature-gated on `Features.teleport_confirm`.

The tick that confirms a teleport does not also simulate movement, so the client never sends two
movement packets in one tick.

### PhysicsTickEvent

```python
from pyflayer.events import PhysicsTickEvent


@bot.event
async def on_physics_tick(event: PhysicsTickEvent) -> None:
    print(event.tick, event.position, event.on_ground)
```

It carries `tick`, `position` and `on_ground`. M5's `tasks.loop(ticks=...)` will wait on this
counter rather than wall time.

### Limitations

- No status effects, attributes, flight or elytra are fed into the engine yet.
- The bot does not model server velocity packets for its own player; reconciliations are limited to
  server positions/teleports.
- The 10-minute vanilla/Paper anti-cheat soak is a live-server gate and has not been run here.

## Chat safety

`ChatQueue` is a token bucket: it allows a burst of 3 messages, then one message per 1.1 s, and
splits ordinary chat over 256 characters, which avoids the usual spam kicks. `bot.chat()` preserves
a leading `/` and sends it as a server command without splitting; ordinary chat is split. Use
`bot.send_command()` when the input is definitely a command. `commands.Context.reply()` and
`.send()` strip leading `/` so command output cannot become a server command. Messages are unsigned
(correct for 1.8); servers using
`enforce-secure-profile` on 1.19.1+ will reject them when those versions are supported.

## PikaNetwork

PikaNetwork is offline-mode and accepts `1.8`–newer clients. With the 1.8.9 reference version the
bot joins, spawns and chats without encryption; the server asks new names to `/register` or
`/login`, which the caller sends through `bot.send_command()`.

PikaNetwork's proxy does not forward a normal player tab list to this client: in live 1.8.9 probes
`player_info` contained only the bot itself, so `bot.players` was `{bot_uuid: ...}` even while other
players were visible as entities. This is server behaviour, not a decode failure; do not treat an
empty-looking tab list as a protocol bug.
