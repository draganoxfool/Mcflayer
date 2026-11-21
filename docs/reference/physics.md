# `pyflayer.physics`

A deterministic, side-effect-free simulation of a Minecraft Java player. It reads only block
queries from the world and never sends packets, so the same step can run inside the bot loop, a
test with `FakeClock`, or a worker thread over a `WorldSnapshot`.

```python
from pyflayer.physics import PhysicsEngine, PlayerState, ControlState, TickDriver, Vec3
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Quick example

```python
import asyncio

from pyflayer import ControlState, PhysicsEngine, PlayerState, TickDriver, Vec3
from pyflayer._internal.clock import MonotonicClock
from pyflayer.data import McData
from pyflayer.world import World

world = World(McData.load("1.8.9"))
state = PlayerState(Vec3(8.5, 64.0, 8.5), on_ground=True)
engine = PhysicsEngine()

state = engine.step(state, ControlState(forward=1.0, sprint=True, yaw=0.0), world)
print(state.position, state.velocity, state.on_ground)

# Drive at 20 TPS
async def tick(tick_number: int) -> None:
    global state
    state = engine.step(state, ControlState(forward=1.0, yaw=0.0), world)
    print(f"Tick {tick_number}: {state.position}")

asyncio.run(TickDriver(MonotonicClock()).run(tick))
```

## Coordinate conventions

| Value | Convention |
|---|---|
| `position` | **Feet** position, the bottom centre of the hitbox. This matches the protocol position packet. |
| Hitbox | `0.6 x 1.8 x 0.6`, centred on X/Z; eye height `1.62`. |
| Yaw | Degrees, Minecraft style: `0` faces south (`+Z`), `90` faces west (`-X`), `180` faces north. |
| Pitch | Degrees; negative looks up, positive looks down. |
| `forward` | Positive towards the facing direction. |
| `strafe` | Positive to the player's **left**. |
| Units | Blocks and ticks. Velocity is blocks per tick, not per second. |

The engine clamps `forward` and `strafe` to `-1..1`; values beyond that are ignored rather than amplified.

## API reference

### `class PlayerState`

```python
PlayerState(
    position: Vec3,
    velocity: Vec3 = Vec3(0.0, 0.0, 0.0),
    yaw: float = 0.0,
    pitch: float = 0.0,
    on_ground: bool = False,
    sprinting: bool = False,
    sneaking: bool = False,
    in_water: bool = False,
    in_lava: bool = False,
    in_web: bool = False,
    on_ladder: bool = False,
)
```

Immutable input and output of one tick. `PhysicsEngine.step()` returns a **new** `PlayerState`; it
never mutates the one passed in, which makes snapshotting and replay cheap.

**Attributes**

| Attribute | Type | Meaning |
|---|---|---|
| `position` | `Vec3` | Feet position. |
| `velocity` | `Vec3` | Blocks per tick. |
| `yaw` / `pitch` | `float` | Look direction in degrees. |
| `on_ground` | `bool` | The last collision ended on a support. |
| `sprinting` / `sneaking` | `bool` | The input state used on the last tick. |
| `in_water` / `in_lava` | `bool` | Medium flags sampled after the last step. |
| `in_web` / `on_ladder` | `bool` | Web/ladder flags sampled after the last step. |

**Properties**

- `box` — the `AABB` at `position`.
- `eye_position` — `position + (0, 1.62, 0)`, used by raycasts and look packets.

> The medium flags describe the position **after** the step and drive the **next** tick. Do not
> overwrite them from network state; let the engine sample them.

### `class ControlState`

```python
ControlState(
    forward: float = 0.0,
    strafe: float = 0.0,
    jump: bool = False,
    sneak: bool = False,
    sprint: bool = False,
    yaw: float = 0.0,
    pitch: float = 0.0,
)
```

Input sampled at one tick boundary. `jump` is an edge-triggered request: provide it on exactly one
tick, not continuously. `sprint` and `sneak` are mutually exclusive in the engine — sneak wins.

`Bot.jump()` implements the edge automatically; `Bot.set_movement()` keeps continuous input.

### `class PhysicsEngine`

```python
PhysicsEngine(*, step_height: float = 0.6, gravity: float = 0.08)
```

A pure 1.8-style simulation. The constructor exists so tests and future versions can override the
step height and gravity without global mutation.

#### `step(state, controls, world) -> PlayerState`

Advances the player by exactly one 20 TPS tick.

| Parameter | Type | Description |
|---|---|---|
| `state` | `PlayerState` | Current pose and velocity. |
| `controls` | `ControlState` | Continuous input and look direction. |
| `world` | `WorldReader` | Object exposing `block_at(BlockPos)` and `collision_boxes(BlockPos)`. `World` and `WorldSnapshot` both qualify. |

The order of operations follows vanilla `LivingEntity.travel`:

1. Apply jump (ground, water/lava, ladder).
2. Choose acceleration: ground friction, air, or liquid.
3. Apply input along the yaw vector.
4. Clamp ladder velocity.
5. Move with swept collision Y → X → Z and attempt a `0.6` step-up.
6. Apply collision response and the horizontal move multiplier for cobwebs.
7. Apply liquid drag or gravity + air drag + ground friction.
8. Sample the medium at the new position and return a new `PlayerState`.

**Raises:** nothing for ordinary world gaps. Unloaded chunks are treated as air by
`World.collision_boxes()`; the bot separately stops simulating when its own chunk is not loaded.

**Example — measure terminal walk speed:**

```python
state = PlayerState(Vec3(0.0, 64.0, 0.0), on_ground=True)
for _ in range(20):
    state = engine.step(state, ControlState(forward=1.0, yaw=0.0), flat_world)
assert abs(state.velocity.z - 0.11785842372264366) < 1e-6
```

### `class TickDriver`

```python
TickDriver(clock: Clock, *, tps: int = 20, max_catch_up: int = 2)
```

Runs a coroutine on absolute deadlines without drift. The bot owns one driver per connection; tests
inject `FakeClock` to make the loop deterministic.

**Attributes**

| Attribute | Meaning |
|---|---|
| `clock` | Injected time source (`Clock`). |
| `tps` | Target ticks per second (`20`). |
| `max_catch_up` | Late ticks allowed before the backlog is dropped (`2`). |
| `tick` | Completed callbacks. |
| `dropped_ticks` | Ticks skipped because the loop was too far behind. |
| `catch_up_ticks` | Ticks that started at least one full interval late but inside the budget. |
| `catch_up_events` | Same count as `catch_up_ticks`, for event-style logging. |
| `jitter` | Standard deviation of observed intervals, in seconds. |
| `jitter_ms` | `jitter` in milliseconds. |
| `jitter_p99_ms` | 99th percentile absolute deviation from the target interval, in milliseconds. |
| `measured_tps` | Ticks per second since `run()` started (or `0.0`). |

**Methods**

| Method | Meaning |
|---|---|
| `run(callback)` — awaits `callback(tick_number)` until `stop()` or cancellation. Deadlines are advanced by `1 / tps`, so callback duration does not accumulate drift. |
| `stop()` — exits after the current callback. Safe to call from inside the callback. |

**Catch-up policy.** If the loop is more than `max_catch_up` intervals behind, it keeps the newest
`max_catch_up` ticks and **drops** the rest, resynchronizing to the wall clock. A stalled event loop
therefore cannot burst a long run of movement packets, which is what triggers "moved too quickly".

!!! note "Jitter measured on this machine"
    A 100-tick idle run with `MonotonicClock` measured **19.994 TPS** with **p99 jitter 0.83 ms**,
    **0 dropped ticks** and **0 catch-up ticks** (roadmap gate: p99 < 5 ms). The exact number depends
    on the host; `TickDriver.jitter_p99_ms` reports it for your own deployment.

**Cancellation.** `run()` is cancellation-safe: `FakeClock.pending` returns to zero after a cancelled
driver. The bot calls `driver.stop()` and cancels its task in `Bot.close()`.

### `move_box(box, delta, world, *, step_height=0.6, can_step=True) -> MoveResult`

Swept AABB resolver used by the engine and exposed for tools and tests.

1. Clips Y, then X, then Z against every block collision box in the swept range.
2. Translates the **whole** hitbox to the contact plane, preserving its dimensions.
3. Reports `hit_x`, `hit_y`, `hit_z` and `on_ground`.
4. When horizontal motion is blocked and `can_step` is true, raises the box by at most
   `step_height`, retries the horizontal move, and drops it back onto the step.

`MoveResult` fields: `box` (final AABB), `delta` (`Vec3` applied per axis), `hit_x`, `hit_y`,
`hit_z`, `on_ground`.

### `Medium` and `sample_medium(world, position, *, on_ground)`

`Medium` is a frozen record of the environment around the feet/waist/head cells:

| Field | Default | Meaning |
|---|---|---|
| `in_water` | `False` | Water at feet, waist or head. |
| `in_lava` | `False` | Lava or flowing lava in those cells. |
| `in_web` | `False` | Cobweb in those cells. |
| `on_ladder` | `False` | Ladder in those cells. |
| `slipperiness` | `0.6` | Slipperiness of the supporting block. |
| `speed_multiplier` | `1.0` | Movement speed multiplier of the supporting block. |

Known block values from the vendored 1.8 data:

| Block | Slipperiness | Speed multiplier |
|---|---|---|
| Ice / packed ice | `0.98` | `1.0` |
| Slime block | `0.8` | `1.0` |
| Soul sand | `0.6` | `0.4` |
| Everything else | `0.6` | `1.0` |

### Constants

| Name | Value | Meaning |
|---|---|---|
| `PLAYER_WIDTH` | `0.6` | Hitbox width/depth. |
| `PLAYER_HEIGHT` | `1.8` | Hitbox height. |
| `PLAYER_EYE_HEIGHT` | `1.62` | Eye offset from the feet. |
| `STEP_HEIGHT` | `0.6` | Maximum automatic step-up. |
| `PLAYER_SPEED` | `0.1` | Base ground acceleration. |
| `GRAVITY` | `0.08` | Per-tick gravity. |
| `JUMP_VELOCITY` | `0.42` | Initial jump velocity. |

`PhysicsEngine` also uses air acceleration `0.02`, air drag `0.98`, sprint multiplier `1.3`, sneak
multiplier `0.3`, and ground friction `slipperiness * 0.91`.

## Fidelity to vanilla 1.8.9

The trace suite compares against `prismarine-physics` 1.11.1 with `minecraft-data` 3.75.0, the
engine Mineflayer uses. Ten scripted 20-tick courses are recorded on a flat 1.8.9 world:

| Trace | What it checks |
|---|---|
| `walk_flat` | Ground acceleration and terminal walk speed. |
| `sprint_flat` | Sprint multiplier. |
| `sneak_flat` | Sneak multiplier. |
| `jump` | Jump apex and landing. |
| `sprint_jump` | Sprint jump boost along the facing vector. |
| `ice` | Slipperiness `0.98`. |
| `slime` | Slipperiness `0.8`. |
| `cobweb` | Delta scaling and velocity reset. |
| `water` | Water drag and buoyancy. |
| `lava` | Lava drag and buoyancy. |

Every trace matches position, `on_ground`, `in_water` and `in_lava` within **`1e-6` per tick**. The
fixture records positions rounded to `1e-9`; regenerate it with the pinned packages:

```bash
cd tools/mineflayer_oracle
npm install
npm run generate
```

Reference values:

- Walking terminal velocity: `0.11785842372264366` blocks/tick.
- Standing jump from feet Y=`64`: peak `65.25220334025373` (delta `1.25220334025373`).
- Sprint jump from a slab at `64.5`: peak `65.752203`.

## Additional engine tests

The oracle world only carries full-block shapes, so these cases run directly against the vendored
1.8 collision data:

- **Stairs** — a bottom oak stair (`metadata = 2`) is climbed with the `0.6` step-up.
- **Ladders** — pushing into a ladder climbs at `0.2`; sneaking holds the player in place. This is
  the 1.8 behaviour; jump-to-climb is 1.14+ and is deliberately not enabled.
- **Soul sand** — the supporting block applies the vanilla `0.4` speed multiplier.
- **Swept collision** — the whole hitbox is translated, so it never shrinks or tunnels through a
  wall.
- **Randomised invariants** — 300 ticks of seeded random input on a walled arena: the player never
  intersects a solid block and `on_ground` always has a supporting collision box.
- **Driver timing** — exact `[0.05, 0.10, 0.15]` deadlines under `FakeClock`, bounded catch-up,
  p99 jitter, and cancellation safety.

## Divergences and deferred work

These are intentional and recorded against vanilla `LivingEntity.travel`; none are silent.

- **Soul sand.** `prismarine-physics` 1.8 only samples blocks intersecting the hitbox, so it never
  applies the supporting-block slowdown. pyflayer implements the vanilla `BlockSoulSand` behaviour,
  which is why soul sand is covered by an engine test rather than the oracle trace.
- **Honey blocks.** They do not exist in 1.8; the honey gate moves to the first 1.15+ dataset.
- **Status effects and attributes.** Speed, jump boost, levitation, slow falling, Depth Strider and
  Dolphin's Grace are not modelled yet. `bot.attributes` records the server values, but the engine
  does not read them.
- **Flight and elytra.** Player abilities and elytra physics are not implemented.
- **Liquid exit impulse and bubble columns.** Entering/leaving a liquid uses drag and buoyancy only;
  bubble columns and the `0.3` out-of-liquid impulse are deferred.
- **Anti-cheat soak.** The code and unit gates are complete, but the roadmap's 10-minute scripted
  run on vanilla/Paper is a live-server check and has not been executed in this environment.

The bot-side packet cadence and teleport reconciliation are documented in
[Bot → Movement and physics](bot.md#movement-and-physics); the remaining backlog is in
[`docs/tasks.md`](../tasks.md).