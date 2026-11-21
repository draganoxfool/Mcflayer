# Architecture

Source of truth for module boundaries, contracts and data flow. If the roadmap or a prompt
conflicts with this document, this document wins.

## Design stance: discord.py-inspired, not a port

mcflayer borrows discord.py's *shape*, not its surface: decorators for handlers, cogs that group
commands and listeners, `tasks.loop`, a typed event bus, converters and checks. That familiarity is
the feature. Everything else is deliberately out of scope.

**What carries over**

- `Bot` as the composition root, `Cog` as the unit of grouping, `@bot.event` / `@Cog.listener()`.
- `@commands.command()` signatures parsed into typed parameters, converters, `Greedy`, `Range`, flags.
- Checks, cooldowns, per-command error handlers, generated help.
- `tasks.loop` with `before_loop` / `after_loop`.
- Extension modules with `setup()` / `teardown()` and atomic hot reload.
- OOP throughout: state lives on objects, not in module globals.

**What does NOT carry over (by design)**

- `command_prefix`. Minecraft has no implicit prefix. Prefixes are opt-in via `commands.Bot(prefix="!")`;
  a message is also a command when addressed to the bot (whisper or name mention) or when code calls
  `bot.dispatch_command(...)`. Passing `command_prefix=` raises a clear `TypeError` (see ADR-11).
- Slash commands, `app_commands`, interactions, views/modals/buttons, webhooks, threads.
- Permissions, roles, guilds: Minecraft has none of these; `is_owner` plus world checks cover the need.
- The `Client`/`Bot` split, `Intents`, sharding, gateway/resume semantics, discord.py-compatible imports.
- Feature parity as a goal. If a discord.py concept has no Minecraft meaning, it is not implemented.

Compatibility is social, not binary: code written for discord.py reads naturally, but
`import pyflayer.ext as commands` is not a drop-in replacement and the project will not pretend
otherwise. `docs/migrating-from-discordpy.md` lists every behaviour kept and every one dropped.

## Performance & compiled fast paths

Two-tier rule: correctness in Python first, then an optional native accelerator behind the same API.

- The public API stays pure Python. Native modules are private (`pyflayer._native.*`) and imported
  through one guarded `_native/__init__.py` that falls back to the pure-Python implementation.
- Candidates, in value order: paletted chunk decode, NBT parse, VarInt/frame scanning, the A* inner
  loop, and the physics tick. These are the only places where per-object Python cost shows up inside
  a 50 ms tick budget.
- Implementation options, in order of preference: `numpy` vectorization (already a hard dependency,
  no new toolchain), Rust via PyO3/maturin (`abi3` wheels), Cython, then C++/pybind11. A compiled
  kernel must ship prebuilt wheels for the CI matrix; "install a compiler" is not an acceptable
  requirement for users.
- No native module is mandatory at runtime. `pip install mcflayer` works everywhere;
  `pip install mcflayer[native]` adds accelerator wheels. The same golden tests run against both paths.
- CI benchmark gate on decode, A* and tick; a native path that is not measurably faster is removed.
- Process offload is not the default. `run_cpu` uses a thread for numpy/GIL-releasing work and a
  process only for pure-Python CPU burns, because snapshots are immutable (ADR-6).

## Section 1: Directory Structure & Module Responsibilities

### 1.0 Architectural Decision Records (the "do not drift" list)

| # | Decision |
|---|---|
| ADR-1 | Single-threaded asyncio is the concurrency model. Chunk and world memory is mutated only on the event loop. CPU-heavy work (A*, big zlib inflate) is offloaded to read-only snapshots. |
| ADR-2 | Layered imports are enforced by `import-linter` in CI. Lower layers never import higher ones. Cross-layer calls go through `typing.Protocol` interfaces defined in the lower layer. |
| ADR-3 | The protocol layer knows nothing about Minecraft game semantics. It emits typed packet objects and nothing else. |
| ADR-4 | State sync happens before user code. Internal handlers (priority ≥ 1000) mutate world/entity/inventory state synchronously inside `dispatch`. User listeners run afterwards. When your `on_block_update` fires, `bot.world` is already updated. |
| ADR-5 | Only the lease holder may write movement or look controls. The physics engine is the sole producer of movement packets. Actions never send movement packets. |
| ADR-6 | Chunk sections are persistent and copy-on-write. Mutation replaces the section object. Snapshots are cheap pointer copies and are safe to read from worker threads. |
| ADR-7 | The version-specific schema is data-driven (`minecraft-data`) by default, with hand-written "native codecs" for hot or unrepresentable packets. |
| ADR-8 | Time is injected (`Clock` Protocol). Nothing calls `time.monotonic()` or `asyncio.sleep` directly outside `_internal/clock.py`. This makes tick loops, tasks and cooldowns deterministically testable. |
| ADR-9 | Every public async API is cancellation-safe. `CancelledError` is never swallowed. Cleanup lives in `finally`. |
| ADR-10 | Errors form one tree rooted at `PyFlayerError`. No bare `Exception` is raised in library code. |
| ADR-11 | `ext.commands` is discord.py-inspired, never a port. Prefixes are opt-in (`prefix=`), the discord.py spelling `command_prefix=` is rejected, and there are no slash commands, permission hierarchy or feature parity. Commands are dispatched by prefix, addressing, `trigger=`, or `bot.dispatch_command()`. |
| ADR-12 | Hot paths have an optional native implementation behind a private, guarded import. Native code is an optimization, never a requirement; both paths pass the same golden tests. |

### 1.1 Layer map

```
L8  swarm            ── BotCluster, SharedWorld wiring, coordination
L7  ext.commands, ext.tasks        ── discord.py-inspired layer (opt-in prefix, not a port)
L6  bot              ── composition root: Bot, handlers (packet → state)
L5  actions, pathfinder            ── behaviours (depend on ActionHost Protocol, not Bot)
L4  physics          ── 20-TPS simulation (reads world; no protocol)
L3  world            ── chunks, blocks, entities, dimensions
L2  protocol         ── bytes ⇄ packets, state machine, auth, crypto
L1  data, events     ── minecraft-data registries; typed event bus
L0  errors, models, _internal ── pure values, clocks, utilities (stdlib/numpy only)
```

Allowed imports: a module may import only from its own layer (same package) or lower layers.
Exceptions: `world` may import `data` for registries, and `physics` may import `world` read-only views.

### 1.2 Package layout

```
pyflayer/
├── pyproject.toml            # hatchling, PEP 621, extras: [auth], [dev]
├── .importlinter             # layer contracts (ADR-2)
├── data/                     # git submodule: PrismarineJS/minecraft-data (pinned SHA)
├── tools/
│   ├── compile_data.py       # optional: precompile JSON → cache
│   ├── record_session.py     # capture packet streams (.pfr) from a real server
│   └── mineflayer_oracle/    # Node scripts producing golden fixtures from prismarine-*
├── tests/ (unit/, integration/, golden/, fixtures/)
└── src/pyflayer/
    ├── __init__.py           # curated public API, __all__
    ├── py.typed
    ├── errors.py
    ├── _internal/
    │   ├── clock.py          # Clock Protocol, MonotonicClock, FakeClock
    │   ├── cpu.py            # run_cpu(): thread/process offload helper with budget logging
    │   ├── log.py
    │   └── util.py
    ├── models/
    │   ├── vec3.py           # Vec3 (float), BlockPos (int), ChunkPos, SectionPos
    │   ├── aabb.py
    │   ├── enums.py          # Dimension, GameMode, Face, Hand, Difficulty, Pose
    │   ├── text.py           # ChatComponent, plain-text flattening, translate keys
    │   ├── items.py          # ItemStack (+ components placeholder)
    │   └── protocols.py      # shared Protocols: WorldReader, ActionHost, PacketSink
    ├── data/
    │   ├── loader.py         # McData.load(version) via dataPaths.json, cached
    │   ├── schema.py         # msgspec.Struct types for blocks/items/entities/...
    │   ├── registries.py     # Block/Item/Entity/Biome/Effect registries, state-id tables
    │   ├── shapes.py         # collision shape tables indexed by block state id
    │   ├── features.py       # features.json evaluation: mc.supports("...")
    │   └── versions.py       # version parsing, protocol ↔ minecraftVersion mapping
    ├── events/
    │   ├── bus.py            # EventBus, Subscription, expect()/wait_for
    │   ├── base.py           # Event base class, naming rules
    │   └── catalog.py        # all public event dataclasses (ChatEvent, SpawnEvent...)
    ├── protocol/
    │   ├── varint.py         # VarInt/VarLong encode/decode
    │   ├── buffer.py         # PacketReader / PacketWriter (memoryview, zero-copy)
    │   ├── types/            # primitives: nbt.py, position.py, slot.py, uuid.py, bitset.py
    │   ├── protodef.py       # schema → codec compiler
    │   ├── native/           # hand-written codecs for hot/unrepresentable packets
    │   ├── registry.py       # (version, state, direction) → id ⇄ name ⇄ codec
    │   ├── framing.py        # length prefix, compression, size limits
    │   ├── crypto.py         # AES-128-CFB8 stream wrapper
    │   ├── connection.py     # asyncio streams, TCP_NODELAY, SRV, backpressure
    │   ├── state.py          # ConnectionState enum + legal transitions
    │   ├── client.py         # ProtocolClient: handshake→login→config→play machine
    │   ├── status.py         # Server List Ping
    │   └── auth/
    │       ├── base.py       # AuthProvider Protocol → Session(profile, token)
    │       ├── offline.py
    │       ├── microsoft.py # device-code → XBL → XSTS → MC services
    │       └── session_join.py # sessionserver join + server-hash
    ├── world/
    │   ├── palette.py        # PalettedContainer (single/indirect/direct), bit packing
    │   ├── section.py        # ChunkSection (immutable-by-convention)
    │   ├── chunk.py          # ChunkColumn, block entities, heightmaps
    │   ├── world.py          # World (one dimension): chunk map, get/set, find, snapshots
    │   ├── view.py           # WorldView (read-only), WorldSnapshot
    │   ├── store.py          # ChunkStore (refcounted), WorldKey
    │   ├── entities.py       # Entity, EntityTracker, metadata
    │   ├── block.py          # Block flyweights from registry
    │   └── raycast.py        # voxel raycast (DDA) over shapes
    ├── physics/
    │   ├── tick.py           # TickDriver: drift-compensated 20 TPS loop
    │   ├── state.py          # PlayerState (pos, vel, onGround, flags, effects)
    │   ├── controls.py       # ControlState (fwd/back/left/right/jump/sprint/sneak)
    │   ├── engine.py         # PhysicsEngine.step(): pure function of (state, controls, world)
    │   ├── collision.py      # swept AABB resolution, step-up
    │   ├── media.py          # ground/air/water/lava/ladder/web/honey/ice/slime rules
    │   └── attributes.py     # movement speed, effects, enchant modifiers
    ├── pathfinder/
    │   ├── goals.py          # Goal hierarchy (static + dynamic)
    │   ├── moves.py          # Movement generators (traverse, ascend, descend, fall...)
    │   ├── costs.py          # tick-based cost model, Settings
    │   ├── astar.py          # time-sliced A* with open-set heap & node pool
    │   ├── planner.py        # Planner: async search on snapshots, partial paths
    │   ├── executor.py       # PathExecutor: follows path via leases, replans
    │   └── cache.py
    ├── actions/
    │   ├── scheduler.py      # ActionScheduler, Priority, Resource, Lease
    │   ├── base.py           # Action, ActionHandle, results
    │   ├── dig.py  place.py  interact.py  equip.py  eat.py  attack.py  look.py  goto.py
    │   └── survival.py       # SurvivalMonitor (health, air, fire, void, hunger)
    ├── bot/
    │   ├── bot.py            # Bot: facade; owns Protocol/World/Physics/Scheduler
    │   ├── handlers/         # login.py chunks.py entities.py inventory.py health.py movement.py chat.py ...
    │   ├── lifecycle.py      # connect/reconnect/shutdown with TaskGroup
    │   ├── inventory.py      # Window, Slot cache, click transaction state
    │   └── chat.py           # ChatParser (system/player/disguised), outbound ChatQueue
    ├── ext/
    │   ├── commands/
    │   │   ├── bot.py        # commands.Bot(Bot): dispatch rules, cog + extension registry
    │   │   ├── cog.py        # Cog, CogMeta, listener()
    │   │   ├── core.py       # Command, Group, command(), group()
    │   │   ├── context.py    # Context
    │   │   ├── view.py       # StringView tokenizer
    │   │   ├── converters.py
    │   │   ├── checks.py     # check, cooldown, max_concurrency, is_owner...
    │   │   ├── flags.py
    │   │   ├── help.py
    │   │   └── errors.py
    │   └── tasks/
    │       └── loop.py       # Loop descriptor, loop() factory
    ├── swarm/
    │   ├── cluster.py        # BotCluster
    │   ├── shared.py         # SharedWorld registry, WorldKey routing
    │   ├── stagger.py        # LoginStaggerPolicy, throttle handling
    │   ├── coordinator.py    # Claims, blackboard, role assignment
    │   └── metrics.py
    └── testing/
        ├── fake_server.py    # in-process protocol server for CI
        ├── replay.py         # .pfr replay driver
        └── oracle.py         # compare against Mineflayer golden traces
```

### 1.3 Module responsibilities & contracts

**`errors`**: One tree: `PyFlayerError` → `ProtocolError` (`MalformedPacket`, `UnknownPacket`, `FramingError`, `CompressionError`, `StateError`), `ConnectionClosed`, `AuthError`, `LoginRejected(reason)`, `KickedError(reason)`, `DataError` (`UnsupportedVersion`, `MissingRegistryEntry`), `WorldError` (`ChunkNotLoaded`, `OutOfWorldBounds`), `ActionError` (`ActionBusy`, `ActionPreempted`, `ActionCancelled`, `ActionFailed`, `LeaseRevoked`), `PathError` (`NoPath`, `PathTimeout`), `ExtensionError` (`ExtensionNotLoaded`, `ExtensionFailed`, …). Each carries structured fields, not just strings.

**`models`**: Pure, slotted, frozen dataclasses. No I/O, no registries, no asyncio. `models/protocols.py` holds the `Protocol` interfaces that let upper layers depend downward. Examples: `WorldReader.block_state_id(pos)`, `ActionHost`, `PacketSink.send(packet)`.

**`data`**: Loads and indexes `minecraft-data` for one version into an immutable `McData`. Resolves `dataPaths.json`, builds block-state-id tables, collision-shape tables and `features`. It imports nothing from `protocol` or `world`. `protocol/protodef.py` consumes `McData.protocol_schema` as plain data.

**`events`**: Typed bus, `wait_for`, `expect`. It imports nothing but `models`. Every layer can raise events by receiving a `Dispatcher` Protocol.

**`protocol`**: Bytes in, `Packet` objects out, and the reverse. It owns framing, compression, encryption, the connection state machine, auth and SLP. It never touches the world or events. It exposes `ProtocolClient.packets() -> AsyncIterator[Packet]` and `send(packet)`.

**`world`**: Owns blocks, chunks, dimensions and entities. It is fed by `bot/handlers` calling its mutation API. It exposes `WorldView` and `WorldSnapshot` for readers. It has no knowledge of packets beyond decoded value types.

**`physics`**: Pure simulation. `engine.step(state, controls, view) -> PlayerState` has no I/O and is deterministic. `TickDriver` calls it at 20 TPS. It consumes `WorldReader`, never `World`.

**`pathfinder`**: Plans on `WorldSnapshot` using the physics constants for cost. It returns a `Path` of `Move` steps. The `executor` drives it through leases.

**`actions`**: Behaviours plus the priority/preemption scheduler. They depend on `ActionHost`, a Protocol implemented by `Bot`. That is how `actions` avoids importing `bot`.

**`bot`**: The composition root and the only place the layers meet. `Bot.__init__` builds `ProtocolClient`, `World`, `PhysicsEngine`, `ActionScheduler`, `EventBus` and the handler set, and registers handlers on the bus at priority ≥ 1000.

**`ext.commands` / `ext.tasks`**: Pure consumers of `Bot`'s public API. Nothing in lower layers imports `ext`.

**`swarm`**: Constructs many `Bot`s with a shared `ChunkStore` and one `TickDriver`. It imports `bot` and `world`.

### 1.4 Data flow (no cycles)

```
INBOUND   socket bytes → framing (decrypt, inflate) → Packet(name, fields)
          → ProtocolClient.packets() ─▶ bot.handlers.<name> (sync, priority ≥1000)
              ├─ world.apply_chunk / apply_block_update / entities.* / inventory.*
              └─ bus.dispatch(PublicEvent)  ─▶ wait_for futures resolve ─▶ user listeners (tasks)

TICK      TickDriver (20 TPS, Clock) → bot.physics_tick()
          → PhysicsEngine.step(PlayerState, ControlState, world.view)
          → handlers.movement.emit_if_changed() → ProtocolClient.send(move packet)
          → bus.dispatch(PhysicsTickEvent)

ACTION    user/ext → bot.scheduler.run(Action, priority)
          → Lease(resources) → writes ControlState / look target / sends interact packets
          → physics consumes controls next tick

PLANNING  Planner.snapshot = world.snapshot(bounds)  (pointer copy)
          → run_cpu(astar, snapshot)  (thread; reads immutable sections)
          → Path → PathExecutor → Lease(MOVEMENT|LOOK) → controls
```

Cycle-breaking tools, in order of preference:
1. Move the shared type down to `models`.
2. Define a `Protocol` in `models/protocols.py`.
3. Use an event.
4. `TYPE_CHECKING`-only import for annotations. This is the last resort and is not allowed for runtime dependencies.

### 1.5 DX north star (the API the whole design must make natural)

```python
import pyflayer
from pyflayer.ext import commands, tasks

bot = commands.Bot(version="1.8.9", prefix="!")   # prefix is optional; addressing also works

class Miner(commands.Cog):
    def __init__(self, bot): self.bot = bot; self.status.start()

    @commands.Cog.listener()
    async def on_spawn(self): ...

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.player)
    async def mine(self, ctx, block: pyflayer.Block, count: commands.Range[int, 1, 64] = 1):
        async with ctx.bot.actions.run(MineBlocks(block, count), priority=Priority.WORK): ...

    @tasks.loop(seconds=30)
    async def status(self): ...

async def setup(bot): await bot.add_cog(Miner(bot))
```

---

## Section 2: Core Technical Specifications & Design Contracts

### 2.1 Event Bus & `wait_for`

**Event model.** Events are `@dataclass(frozen=True, slots=True)` subclasses of `Event`. The dispatch key is the class. The discord.py-style name (`on_block_update`) is derived from the class via a `__event_name__` ClassVar. `ChatEvent` → `on_chat`. The naming convention is borrowed for familiarity; the bus itself is not discord.py's and has no `Intents` or gateway semantics.

```python
E = TypeVar("E", bound=Event)
Listener = Callable[[E], Awaitable[None] | None]

class EventBus:
    def __init__(self, *, clock: Clock, on_error: Callable[[Event, Subscription, BaseException], None] | None = None) -> None: ...

    # registration
    def subscribe(self, event: type[E], listener: Listener[E], *, priority: int = 0,
                  once: bool = False, owner: object | None = None) -> Subscription: ...
    def unsubscribe(self, sub: Subscription) -> None: ...
    def unsubscribe_owner(self, owner: object) -> int:          # cogs / extensions use this

    # emission (sync, never blocks, never raises into the caller)
    def dispatch(self, event: Event) -> None: ...

    # awaiting
    async def wait_for(self, event: type[E], *, check: Callable[[E], bool] | None = None,
                       timeout: float | None = None) -> E: ...         # raises asyncio.TimeoutError
    async def wait_for_any(self, *events: type[Event], check=None, timeout=None) -> Event: ...
    def expect(self, event: type[E], *, check=None, timeout=None) -> Expectation[E]: ...
    def stream(self, event: type[E], *, maxsize: int = 256) -> AsyncIterator[E]: ...
    async def aclose(self) -> None: ...
```

**Dispatch semantics (normative):**
1. `dispatch` runs synchronously in this order: (a) internal state hooks (priority ≥ 1000, run inline, exceptions logged and re-dispatched as `ErrorEvent`); (b) resolve `wait_for` waiters; (c) call user listeners, scheduling awaitable results as tasks tracked in a `set` with done-callbacks.
2. Waiters are resolved before listeners are called. A waiter's `check` raising an exception fails that waiter's future only.
3. Synchronous listeners run inline; async listener results run in their own tracked tasks. One slow async or crashing listener cannot block the bus or other listeners. Crashes become `ErrorEvent(event, listener, exc)`. If no `on_error` consumer exists, they are logged.
4. Per-event FIFO is guaranteed. Cross-event ordering follows dispatch order.
5. `aclose` cancels tracked tasks and awaits them with `asyncio.timeout(5)`.

**Race-free pattern.** `wait_for` after an action can miss the event. Therefore `expect()` is an async context manager that registers the waiter on enter:

```python
async with bot.expect(RespawnEvent, timeout=5) as ev:
    await bot.respawn()
spawned = await ev            # cannot miss, even if it fired during respawn()
```

**Backpressure.** `stream()` uses a bounded queue. Overflow drops the oldest item and increments a counter exposed via `bot.metrics`. It never blocks `dispatch`.

### 2.2 Cog / Command / `tasks.loop`

#### Cog

```python
class CogMeta(type):  # collects @Cog.listener, @command, @loop members into __cog_*__ tables
    ...

class Cog(metaclass=CogMeta):
    qualified_name: str
    def get_commands(self) -> list[Command]: ...
    def get_listeners(self) -> list[tuple[str, Callable]]: ...
    # lifecycle hooks
    async def cog_load(self) -> None: ...
    async def cog_unload(self) -> None: ...
    async def cog_check(self, ctx: Context) -> bool: ...
    async def cog_before_invoke(self, ctx: Context) -> None: ...
    async def cog_after_invoke(self, ctx: Context) -> None: ...
    async def cog_command_error(self, ctx: Context, error: CommandError) -> None: ...
    @staticmethod
    def listener(name: str | None = None) -> Callable[[F], F]: ...
```

#### Extensions (hot reload)

```python
class Bot(pyflayer.Bot):
    async def load_extension(self, name: str, *, package: str | None = None) -> None: ...
    async def unload_extension(self, name: str, *, package: str | None = None) -> None: ...
    async def reload_extension(self, name: str, *, package: str | None = None) -> None: ...
    async def add_cog(self, cog: Cog, *, override: bool = False) -> None: ...
    async def remove_cog(self, name: str) -> Cog | None: ...
```

**Contract:**
- An extension module defines `async def setup(bot)` and optionally `async def teardown(bot)`.
- `load_extension` imports the module, calls `setup`, and on any exception rolls back everything it registered. Tracking is by `owner=` on subscriptions plus a per-extension ledger of commands, cogs and tasks.
- `reload_extension` is atomic. It snapshots the old modules and state, unloads, purges `sys.modules` entries for the extension package subtree only, and re-imports. On failure it restores the old modules and cogs and raises `ExtensionFailed`. A failed reload never leaves the bot half-loaded.
- Unload calls `cog_unload`, cancels cog-owned loops, unsubscribes by owner and removes commands.
- Tests must assert that no listener, task or command leaks after N reload cycles.

#### Dispatch (opt-in prefix plus addressing)

`commands.Bot` subscribes one listener to `ChatEvent` and treats a message as a command when a
configured prefix matches, when it is addressed to the bot, or when dispatch is programmatic:

| Channel | Rule |
|---|---|
| Prefix | `prefix="!"` or a collection; the prefix is stripped before parsing. Works in public chat, whispers, after a mention and after `trigger=`. |
| Whisper | Always addressed. Parse the whole content as `name args...`, with an optional prefix. |
| Public chat | Addressed when the content contains the bot's name as a mentioned token (`<name>` or `@name`, configurable). The mention and optional prefix are stripped before parsing. |
| Programmatic | `await bot.dispatch_command("name args...", author=...)` for tests, cogs and the REPL. |
| `trigger=` | Optional `str` or compiled `re.Pattern` for servers that rewrite chat (e.g. `"bot: "`). Off by default. |

Messages from the bot itself and from the server (`system_chat`) are ignored unless explicitly
enabled. `CommandPrefixError` subclasses `TypeError` and is raised at construction if the discord.py
spelling `command_prefix` is passed, so ported snippets fail loudly instead of silently doing nothing.

```python
class Bot(pyflayer.Bot):
    def __init__(self, *, version: str, prefix: str | Collection[str] | None = None,
                 trigger: str | re.Pattern[str] | None = None,
                 case_insensitive: bool = True, owner_ids: Collection[str] = (), ...) -> None: ...
    async def dispatch_command(self, text: str, *, author: Player | None = None,
                               is_whisper: bool = False, prefix: str | None = None) -> None: ...
    async def process_message(self, message: ChatMessage) -> None: ...   # fed by ChatEvent
```

#### Commands

```python
def command(name: str | None = None, *, aliases: Sequence[str] = (), brief: str | None = None,
            description: str | None = None, hidden: bool = False, enabled: bool = True,
            cls: type[Command] = Command, **attrs) -> Callable[[CommandCallback], Command]: ...
def group(name=None, *, invoke_without_command: bool = False, **attrs) -> ...: ...

class Command(Generic[CogT, P, T]):
    name: str; aliases: tuple[str, ...]; cog: CogT | None; params: OrderedDict[str, Parameter]
    checks: list[Check]; cooldown: CooldownMapping | None
    async def invoke(self, ctx: Context) -> None: ...
    async def can_run(self, ctx: Context) -> bool: ...
    async def prepare(self, ctx: Context) -> None:   # parse+convert args, run checks
    def error(self, coro): ...
    def before_invoke(self, coro): ...
    def after_invoke(self, coro): ...

class Context:
    bot: Bot; message: ChatMessage; author: Player | None; sender_name: str
    invoked_with: str; command: Command | None    # no `prefix`: dispatch is address-based
    args: list[Any]; kwargs: dict[str, Any]; view: StringView
    is_whisper: bool
    async def reply(self, content: str, *, whisper: bool | None = None) -> None:   # via ChatQueue
    async def send(self, content: str) -> None: ...
```

**Parsing.** `StringView` tokenizes quoted strings, backslash escapes and `Greedy`. Positional-only, keyword-only (consume-rest) and `*args` parameter semantics follow discord.py, because they are genuinely convenient — this is the one place we copy it closely. `ChatParser` normalizes `player_chat`, `system_chat`, `disguised_chat` and legacy chat into `ChatMessage(sender, content, is_whisper, signed, raw)`. It uses a configurable regex set for plugin-formatted chat and whispers (`/msg` formats vary per server).

**Converters.**

```python
class Converter(Protocol[T_co]):
    async def convert(self, ctx: Context, argument: str) -> T_co: ...

# built-ins: str,int,float,bool, Vec3, BlockPos (consumes 3 tokens), Player, Entity,
# Block, Item, Dimension, GameMode, Literal[...], Optional[T], Union[...], Greedy[T],
# Range[T, lo, hi], Annotated[T, Converter], Flag converters (--count 5)
```

Resolution order: explicit `Annotated`/`Converter` → built-in map → `Literal`/`Enum` → callable. Failure raises `BadArgument(param, argument, reason)`. Unexpected exceptions are wrapped as `ConversionError`.

**Checks and errors.**

```python
def check(predicate: Callable[[Context], bool | Awaitable[bool]]) -> Callable[[F], F]: ...
def is_owner(); def has_player_nearby(distance: float); def in_dimension(*dims)
def requires_idle()     # fails if the bot holds MOVEMENT lease at priority ≥ WORK
def cooldown(rate: int, per: float, type: BucketType = BucketType.default)
def max_concurrency(number: int, per: BucketType = BucketType.default, *, wait: bool = False)
# BucketType: default, player, global_ (distinct from builtins)
```

Error tree: `CommandError` → `CommandNotFound`, `UserInputError` (`MissingRequiredArgument`, `BadArgument`, `TooManyArguments`, `BadUnionArgument`), `CheckFailure` (`NotOwner`, `CheckAnyFailure`), `CommandOnCooldown(retry_after)`, `MaxConcurrencyReached`, `CommandInvokeError(original)`, `ConversionError`.

Dispatch order is `bot.on_command_error` → `cog_command_error` → `command.error`. The first handler that handles the error stops the chain. An unhandled error is logged.

**Outbound chat safety.** `ChatQueue` enforces a token-bucket rate limit (default 1 message/1.1 s, burst 3) and max length 256. It auto-splits long replies and strips unsafe leading `/`. This avoids server "spam" kicks.

#### `tasks.loop`

```python
def loop(*, seconds: float = MISSING, minutes: float = MISSING, hours: float = MISSING,
         ticks: int = MISSING,                  # Minecraft-native: sync to game ticks
         time: datetime.time | Sequence[datetime.time] = MISSING,
         count: int | None = None, reconnect: bool = True, name: str | None = None) -> Callable[[LF], Loop[LF]]: ...

class Loop(Generic[LF]):                      # descriptor; binds per Cog instance
    current_loop: int; next_iteration: datetime | None
    def start(self, *args, **kwargs) -> asyncio.Task[None]: ...
    def stop(self) -> None            # graceful: finish current iteration
    def cancel(self) -> None          # immediate task.cancel()
    def restart(self, *args, **kwargs) -> None
    def change_interval(self, **kw) -> None
    def is_running(self) -> bool; def failed(self) -> bool; def is_being_cancelled(self) -> bool
    def before_loop(self, coro); def after_loop(self, coro); def error(self, coro)
    def add_exception_type(self, *exc: type[BaseException]) -> None
```

**Semantics.**
- Interval timing is drift-compensated (`next = prev + interval`) using the injected `Clock`.
- `ticks=N` waits on the bot's `PhysicsTickEvent` counter, not wall time.
- `before_loop` conventionally awaits `bot.wait_until_ready()`.
- An unhandled exception goes to the `error` handler. Without one, the loop dies and logs.
- With `reconnect=True`, transient `ConnectionClosed` and `OSError` pause the loop until the bot is ready again.
- Cogs auto-start declared loops on load only if their `start()` was called in `__init__` or `cog_load`. They always cancel on unload.

### 2.3 `World` / `Chunk` memory model

**Coordinates.** Section index is `(y - min_y) >> 4`. Block index inside a section is `(ly << 8) | (lz << 4) | lx` (YZX order). Biomes use 4×4×4 cells.

```python
class PalettedContainer:
    # kind: SINGLE | INDIRECT | DIRECT
    bits_per_entry: int
    palette: tuple[int, ...] | None          # None for DIRECT / SINGLE has 1 entry
    indices: np.ndarray | None               # uint8 (palette ≤ 256) or uint16; None if SINGLE
    def get(self, idx: int) -> int: ...      # resolved global id (block state / biome id)
    def with_set(self, idx: int, value: int) -> "PalettedContainer": ...   # COW, returns new
    def with_sets(self, items: Iterable[tuple[int, int]]) -> "PalettedContainer": ...  # batch
    @classmethod
    def decode(cls, r: PacketReader, *, kind: ContainerKind, features: Features, registry_bits: int) -> Self: ...

@dataclass(frozen=True, slots=True)
class ChunkSection:
    blocks: PalettedContainer; biomes: PalettedContainer; non_air: int

class ChunkColumn:
    pos: ChunkPos; min_y: int; sections: list[ChunkSection]      # replaced, never mutated in place
    block_entities: dict[BlockPos, BlockEntity]; heightmaps: Mapping[str, np.ndarray]
    version: int                                                  # bumped on any mutation
    def block_state_id(self, x: int, y: int, z: int) -> int: ...
    def with_block(self, x, y, z, state_id) -> "ChunkColumn": ...  # in-place column, new section
```

**Decoding rules (must be golden-tested):**
- Block containers: `bits <= 3` → use 4 (indirect), 4–8 → indirect, ≥ 9 → direct with `bits = ceil(log2(len(block_state_registry)))`.
- Biome containers: 1–3 indirect, ≥ 4 direct with bits from the biome registry size. `bits == 0` is a single value.
- **Non-spanning (1.16+):** `per_long = 64 // bits`, `n_longs = ceil(N / per_long)`, and entries never cross a long boundary. Index `i` lives in long `i // per_long` at shift `(i % per_long) * bits`. Longs are big-endian on the wire and entries are LSB-first within a long. Spanning (≤1.15) is gated by `features.supports("blockStateSpansLongs")`-equivalent flags.
- Decode is vectorized with numpy (`np.frombuffer(dtype='>u8')` → shift/mask). No per-block Python loops in the hot path.
- Some versions (≥1.21.5, to be verified) drop the data-array length prefix. This is version-gated in `native/`.

**`World` API.**

```python
class WorldView(Protocol):                    # read-only; physics/pathfinder/actions use this
    min_y: int; height: int
    def block_state_id(self, pos: BlockPos) -> int: ...      # raises ChunkNotLoaded
    def block_state_id_or(self, pos: BlockPos, default: int) -> int: ...
    def block_at(self, pos: BlockPos) -> Block: ...
    def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]: ...
    def is_loaded(self, pos: ChunkPos) -> bool: ...
    def find_blocks(self, *, matching: BlockMatcher, within: float, around: Vec3, count: int = 1) -> list[BlockPos]: ...
    def raycast(self, origin: Vec3, direction: Vec3, max_dist: float, *, include_fluids: bool=False) -> RayHit | None: ...
    def snapshot(self, bounds: Bounds | None = None) -> WorldSnapshot: ...

class World(WorldView):                       # mutable; held by bot handlers only
    def apply_chunk(self, col: ChunkColumn) -> None
    def unload_chunk(self, pos: ChunkPos) -> None
    def set_block_state(self, pos: BlockPos, state_id: int, *, source: object | None = None) -> bool  # False if no-op
    def apply_multi_block_change(self, section: SectionPos, changes: Sequence[tuple[int,int]]) -> None
    def clear(self) -> None                   # dimension change / respawn
```

**Snapshots and thread safety (ADR-6).** `WorldSnapshot` is a dict `{ChunkPos: ChunkColumn-at-version}` (pointer copy, O(columns)). Because sections are replaced rather than mutated, a worker thread reading a snapshot never sees torn data while the loop thread applies updates. Numpy index arrays are set `writeable=False`. A* runs in `run_cpu()` on a snapshot.

**`BotCluster` shared read-only chunk data.**

```python
@dataclass(frozen=True, slots=True)
class WorldKey: server: str; dimension: str

class ChunkStore:                              # one per WorldKey, owned by SharedWorldRegistry
    def acquire(self, bot_id: int, pos: ChunkPos) -> None   # refcount++
    def release(self, bot_id: int, pos: ChunkPos) -> None   # refcount--, drop when 0
    def put(self, col: ChunkColumn, *, from_bot: int) -> bool   # dedup: ignore if same content/version
    def apply_block(self, pos: BlockPos, state_id: int, *, from_bot: int) -> bool

class BotWorldFacade(WorldView):               # per-bot; reads through shared store, tracks own loaded set
```

Rules:
- Bots join a store by `WorldKey`. On a dimension change, the bot's facade rebinds and releases its refs.
- Duplicate chunk arrivals are deduplicated by section content hash. The first bot's decode wins and others only add a ref.
- Block updates are idempotent (`set` to the same state returns `False`). Each bot applies only updates for chunks it currently holds a ref to.
- Entities stay per-bot (visibility differs). The swarm may build a merged, read-only `SwarmEntityView`.
- Memory target: N bots in the same area hold one copy of chunk data.

### 2.4 Action Priority & Preemption Mutex

**Concepts.**

```python
class Resource(enum.Flag):
    MOVEMENT = auto(); LOOK = auto(); HANDS = auto(); WINDOW = auto(); CHAT = auto()

class Priority(enum.IntEnum):
    IDLE = 0; BACKGROUND = 10; WORK = 20; USER = 30; COMBAT = 60; SURVIVAL = 90; EMERGENCY = 100

class OnPreempt(enum.Enum): ABORT = "abort"; RESUME = "resume"; REQUEUE = "requeue"

class Action(Generic[R]):
    resources: ClassVar[Resource]
    name: ClassVar[str]
    on_preempt: ClassVar[OnPreempt] = OnPreempt.ABORT
    async def run(self, lease: Lease) -> R: ...                 # the work
    async def on_preempted(self, lease: Lease, by: ActionHandle) -> None: ...  # fast cleanup, <1 tick of work
    async def checkpoint(self) -> object | None: ...            # for RESUME
```

```python
class ActionScheduler:
    def __init__(self, host: ActionHost, *, clock: Clock) -> None: ...
    def run(self, action: Action[R], *, priority: Priority = Priority.WORK,
            preempt: bool = True, queue: bool = False,
            timeout: float | None = None) -> ActionHandle[R]: ...    # also usable as async CM
    def cancel_all(self, *, reason: str, below: Priority = Priority.EMERGENCY + 1) -> None: ...
    def current(self, resource: Resource) -> ActionHandle | None: ...
    @property
    def idle(self) -> bool: ...

class ActionHandle(Awaitable[R]):
    priority: Priority; state: ActionState    # PENDING|RUNNING|SUSPENDED|DONE|CANCELLED|PREEMPTED|FAILED
    def cancel(self, reason: str = "") -> None
    async def wait(self) -> R                  # raises ActionPreempted / ActionCancelled / ActionFailed

class Lease:                                   # capability token handed to Action.run
    resources: Resource; priority: Priority
    controls: ControlHandle                    # writes raise LeaseRevoked if lease lost
    def critical(self) -> AsyncContextManager[None]      # defers preemption (e.g. mid-placement)
    def child(self, action: Action[R], *, resources: Resource | None = None) -> ActionHandle[R]  # inherits lease
    @property
    def revoked(self) -> bool: ...
```

**Arbitration algorithm (normative):**
1. All arbitration runs under one `asyncio.Lock` in the scheduler. Acquisition of the resource set is all-or-nothing. This rules out deadlocks from partial acquisition.
2. For each requested resource, find the current holder. If the incoming priority is strictly greater than every conflicting holder's priority and `preempt=True`, it preempts them.
3. Preemption is cooperative. The scheduler cancels the holder's task with a `PreemptToken` message. The action's `finally` and `on_preempted` run, bounded by a grace timeout (default 2 ticks). If the holder is inside `lease.critical()`, preemption waits until it exits, bounded by `max_critical_s` (default 1.0), after which the lease is force-revoked.
4. The scheduler converts the `CancelledError` caused by a `PreemptToken` into `ActionPreempted` for awaiters. Any other cancel stays `CancelledError` or becomes `ActionCancelled`. It uses `Task.uncancel()` correctly so an outer cancellation is never lost.
5. On equal or lower priority: `queue=True` enqueues FIFO with priority aging; otherwise it raises `ActionBusy`.
6. After a preemptor completes, suspended `RESUME` actions are restarted in priority order from their `checkpoint()`. `REQUEUE` actions are re-queued. `ABORT` actions stay aborted.
7. A `DeathEvent` calls `cancel_all(reason="death")` below EMERGENCY and holds a barrier until `RespawnEvent`.
8. `Lease.controls` is the only write path to `ControlState` and the look target. Revoking a lease zeroes the controls it set. This is how a mining job stops walking when the bot must flee.

**Survival.** `SurvivalMonitor` is an always-on background component, not a user action. It subscribes to health/food/air/fire/void events and submits `SURVIVAL` actions (`Eat`, `SwimUp`, `LeaveFire`, `AvoidFall`, `Flee`) through the same scheduler. There is no side channel.

### 2.5 Data-driven `minecraft-data` integration

**Source.** Vendor `PrismarineJS/minecraft-data` as a pinned git submodule. `McData.load(version)` resolves via `dataPaths.json` (which handles per-version file inheritance), parses with `msgspec` into frozen `Struct`s, and is cached per `(minecraftVersion, data_commit)`. Optionally it caches a compact preprocessed form in the user cache directory.

```python
@dataclass(frozen=True, slots=True)
class McData:
    version: VersionInfo               # protocol number, minecraftVersion, majorVersion
    features: Features                 # features.json → .supports("name") -> bool
    blocks: BlockRegistry; items: ItemRegistry; entities: EntityRegistry
    biomes: BiomeRegistry; effects: EffectRegistry; foods: FoodRegistry
    shapes: ShapeTable                 # tuple[AABB,...] indexed by block-state id
    protocol: ProtocolSchema           # raw protodef per (state, direction)
    @classmethod
    def load(cls, version: str | int, *, edition: Literal["pc"] = "pc") -> McData: ...
```

**Block states.** Each block entry provides `minStateId`/`maxStateId`/`states`. The registry builds `state_id → (Block, props)` arrays at load. `block_at(pos)` returns a flyweight from a cache indexed by state id (no per-call allocation).

**Collision.** `blockCollisionShapes.json` maps block (and per-state) to shape ids, and shape ids to AABB lists. `ShapeTable.boxes(state_id)` is a precomputed tuple.

**Protocol.**
- `protocol.json` is protodef, per state (`handshaking`, `status`, `login`, `configuration`, `play`) and direction (`toClient`, `toServer`).
- `protodef.py` compiles each packet type into a closure-based codec at load (no schema interpretation per packet). Types include `varint`, `varlong`, ints, floats, `bool`, `UUID`, `pstring`, `buffer`, `array`, `container`, `switch`, `option`, `bitfield`, `bitflags`, `mapper`, `topBitSetTerminatedArray`, `restBuffer`, `nbt`/`optionalNbt`/`anonymousNbt`, `position`, `slot`, `entityMetadata`.
- `native/` overrides specific `(version, state, direction, name)` keys for chunk data, structured item components and others that protodef cannot express faithfully. Unknown packets are skipped by frame length and counted. They are never fatal in Play state.
- Version differences are expressed as `Features` checks and per-version codec registration. There must be no scattered `if version >= (1, 20, 2)` outside `data/` and `protocol/native/`.

**Version support policy.** A support matrix lives in docs. Every supported version must pass the golden suite (chunk decode, login flow against the FakeServer, physics oracle). Adding a version means adding fixtures, not just data.
