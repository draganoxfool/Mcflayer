# PyFlayer Master Blueprint & Prompt Engineering Pack

Save each part as `ARCHITECTURE.md` (Sections 1–2), `ROADMAP.md` (Section 3) and `PROMPTS.md` (Section 4). The notes below are my opinionated deviations from your brief. Veto any of them before you start.

- **Added modules:** `events`, `bot` (composition root), `_internal` (clock, CPU offload) and `testing`. They are needed to keep the dependency graph acyclic.
- **Reference version:** 1.20.4 (protocol 765) for M1–M6, then 1.21.x as a version-adapter milestone. 1.20.4 predates structured item components but already has the Configuration state, so it is the best first target. Verify exact `minecraft-data` coverage for each version when you pin the submodule.
- **Hard dependencies:** `numpy`, `msgspec`, `cryptography`, `httpx`, `dnspython`. Everything else is optional.

---

# ARCHITECTURE.md

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

### 1.1 Layer map

```
L8  swarm            ── BotCluster, SharedWorld wiring, coordination
L7  ext.commands, ext.tasks        ── discord.py-style framework
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
    │   │   ├── bot.py        # commands.Bot(Bot): prefix, cog + extension registry
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

bot = commands.Bot(command_prefix="!", version="1.20.4")


class Miner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status.start()

    @commands.Cog.listener()
    async def on_spawn(self): ...

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.player)
    async def mine(self, ctx, block: pyflayer.Block, count: commands.Range[int, 1, 64] = 1):
        async with ctx.bot.actions.run(MineBlocks(block, count), priority=Priority.WORK):
            ...

    @tasks.loop(seconds=30)
    async def status(self): ...


async def setup(bot):
    await bot.add_cog(Miner(bot))
```

---

## Section 2: Core Technical Specifications & Design Contracts

### 2.1 Event Bus & `wait_for`

**Event model.** Events are `@dataclass(frozen=True, slots=True)` subclasses of `Event`. The dispatch key is the class. The discord.py-style name (`on_block_update`) is derived from the class via a `__event_name__` ClassVar. `ChatEvent` → `on_chat`.

```python
E = TypeVar("E", bound=Event)
Listener = Callable[[E], Awaitable[None] | None]


class EventBus:
    def __init__(
        self,
        *,
        clock: Clock,
        on_error: Callable[[Event, Subscription, BaseException], None] | None = None,
    ) -> None: ...

    # registration
    def subscribe(
        self,
        event: type[E],
        listener: Listener[E],
        *,
        priority: int = 0,
        once: bool = False,
        owner: object | None = None,
    ) -> Subscription: ...
    def unsubscribe(self, sub: Subscription) -> None: ...
    def unsubscribe_owner(self, owner: object) -> int: ...  # cogs / extensions use this

    # emission (sync, never blocks, never raises into the caller)
    def dispatch(self, event: Event) -> None: ...

    # awaiting
    async def wait_for(
        self,
        event: type[E],
        *,
        check: Callable[[E], bool] | None = None,
        timeout: float | None = None,
    ) -> E: ...  # raises asyncio.TimeoutError
    async def wait_for_any(self, *events: type[Event], check=None, timeout=None) -> Event: ...
    def expect(self, event: type[E], *, check=None, timeout=None) -> Expectation[E]: ...
    def stream(self, event: type[E], *, maxsize: int = 256) -> AsyncIterator[E]: ...
    async def aclose(self) -> None: ...
```

**Dispatch semantics (normative):**
1. `dispatch` runs synchronously in this order: (a) internal state hooks (priority ≥ 1000, run inline, exceptions logged and re-dispatched as `ErrorEvent`); (b) resolve `wait_for` waiters; (c) schedule user listeners as tasks, tracked in a `set` with done-callbacks.
2. Waiters are resolved before listeners are scheduled. A waiter's `check` raising an exception fails that waiter's future only.
3. Each listener runs in its own task. One slow or crashing listener cannot block the bus or other listeners. Crashes become `ErrorEvent(event, listener, exc)`. If no `on_error` consumer exists, they are logged.
4. Per-event FIFO is guaranteed. Cross-event ordering follows dispatch order.
5. `aclose` cancels tracked tasks and awaits them with `asyncio.timeout(5)`.

**Race-free pattern.** `wait_for` after an action can miss the event. Therefore `expect()` is an async context manager that registers the waiter on enter:

```python
async with bot.expect(RespawnEvent, timeout=5) as ev:
    await bot.respawn()
spawned = await ev  # cannot miss, even if it fired during respawn()
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

#### Commands

```python
def command(
    name: str | None = None,
    *,
    aliases: Sequence[str] = (),
    brief: str | None = None,
    description: str | None = None,
    hidden: bool = False,
    enabled: bool = True,
    cls: type[Command] = Command,
    **attrs,
) -> Callable[[CommandCallback], Command]: ...
def group(name=None, *, invoke_without_command: bool = False, **attrs) -> ...: ...


class Command(Generic[CogT, P, T]):
    name: str
    aliases: tuple[str, ...]
    cog: CogT | None
    params: OrderedDict[str, Parameter]
    checks: list[Check]
    cooldown: CooldownMapping | None

    async def invoke(self, ctx: Context) -> None: ...
    async def can_run(self, ctx: Context) -> bool: ...
    async def prepare(self, ctx: Context) -> None: ...  # parse+convert args, run checks
    def error(self, coro): ...
    def before_invoke(self, coro): ...
    def after_invoke(self, coro): ...


class Context:
    bot: Bot
    message: ChatMessage
    author: Player | None
    sender_name: str
    prefix: str
    invoked_with: str
    command: Command | None
    args: list[Any]
    kwargs: dict[str, Any]
    view: StringView
    is_whisper: bool

    async def reply(
        self, content: str, *, whisper: bool | None = None
    ) -> None: ...  # via ChatQueue
    async def send(self, content: str) -> None: ...
```

**Parsing.** `StringView` tokenizes quoted strings, backslash escapes and `Greedy`. Positional-only, keyword-only (consume-rest) and `*args` parameter semantics follow discord.py. `ChatParser` normalizes `player_chat`, `system_chat`, `disguised_chat` and legacy chat into `ChatMessage(sender, content, is_whisper, signed, raw)`. It uses a configurable regex set for plugin-formatted chat and whispers (`/msg` formats vary per server).

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
    palette: tuple[int, ...] | None  # None for DIRECT / SINGLE has 1 entry
    indices: np.ndarray | None  # uint8 (palette ≤ 256) or uint16; None if SINGLE

    def get(self, idx: int) -> int: ...  # resolved global id (block state / biome id)
    def with_set(self, idx: int, value: int) -> "PalettedContainer": ...  # COW, returns new
    def with_sets(self, items: Iterable[tuple[int, int]]) -> "PalettedContainer": ...  # batch
    @classmethod
    def decode(
        cls, r: PacketReader, *, kind: ContainerKind, features: Features, registry_bits: int
    ) -> Self: ...


@dataclass(frozen=True, slots=True)
class ChunkSection:
    blocks: PalettedContainer
    biomes: PalettedContainer
    non_air: int


class ChunkColumn:
    pos: ChunkPos
    min_y: int
    sections: list[ChunkSection]  # replaced, never mutated in place
    block_entities: dict[BlockPos, BlockEntity]
    heightmaps: Mapping[str, np.ndarray]
    version: int  # bumped on any mutation

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
    MOVEMENT = auto()
    LOOK = auto()
    HANDS = auto()
    WINDOW = auto()
    CHAT = auto()


class Priority(enum.IntEnum):
    IDLE = 0
    BACKGROUND = 10
    WORK = 20
    USER = 30
    COMBAT = 60
    SURVIVAL = 90
    EMERGENCY = 100


class OnPreempt(enum.Enum):
    ABORT = "abort"
    RESUME = "resume"
    REQUEUE = "requeue"


class Action(Generic[R]):
    resources: ClassVar[Resource]
    name: ClassVar[str]
    on_preempt: ClassVar[OnPreempt] = OnPreempt.ABORT

    async def run(self, lease: Lease) -> R: ...  # the work
    async def on_preempted(
        self, lease: Lease, by: ActionHandle
    ) -> None: ...  # fast cleanup, <1 tick of work
    async def checkpoint(self) -> object | None: ...  # for RESUME
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
    version: VersionInfo  # protocol number, minecraftVersion, majorVersion
    features: Features  # features.json → .supports("name") -> bool
    blocks: BlockRegistry
    items: ItemRegistry
    entities: EntityRegistry
    biomes: BiomeRegistry
    effects: EffectRegistry
    foods: FoodRegistry
    shapes: ShapeTable  # tuple[AABB,...] indexed by block-state id
    protocol: ProtocolSchema  # raw protodef per (state, direction)

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

---

# ROADMAP.md

## Section 3: Phased Engineering Roadmap

Global exit gate for every milestone: `ruff`, `mypy --strict` and `pyright` clean, `import-linter` clean, tests green on Python 3.11/3.12/3.13, coverage ≥ 90% on new modules, public API changes documented, and a short Handoff Notes file for the next session.

### M1: Transport, VarInt Framing, Data Loader, Codec Compiler

**Scope.** Scaffolding, `models` basics, `errors`, `_internal`, `data` loader, `protocol` primitives, framing, compression, encryption, status ping, protodef compiler.

**Definition of Done**
- Can ping a real server (SLP) and print MOTD, version and players. SRV resolution works.
- VarInt/VarLong, string, UUID, position, NBT (network and file variants) round-trip under property tests.
- Framing handles partial reads, compression thresholds and AES-CFB8 over a loopback socket.
- `McData.load("1.20.4")` loads and indexes all registries. The protodef compiler can encode and decode every handshake/status/login/configuration packet for 1.20.4 against golden bytes.

**Testing.**
- Hypothesis round-trips for VarInt (including negative values and 5-byte limits), strings and NBT.
- Golden byte vectors from the wiki.vg-documented examples and from packets recorded with `tools/record_session.py`.
- Fuzz: random truncation and bit flips must raise `MalformedPacket`, never crash or hang.
- A zlib-bomb test must be rejected at the declared limit.
- Loopback server test for framing with a split-read adversarial socket (1-byte reads).

### M2: Login/Configuration/Play State Machine, Event Bus, Minimal Bot

**Scope.** `ProtocolClient`, auth (offline and Microsoft), `events`, `bot` skeleton, keep-alive, chat I/O, respawn.

**Definition of Done**
- Joins an offline-mode vanilla 1.20.4 server and an online-mode server with a Microsoft account. Reaches Play, stays connected for 30 minutes (keep-alive), sends and receives chat, handles death and respawn.
- Configuration state completed correctly, including server-initiated re-entry into Configuration.
- `await bot.wait_for(SpawnEvent)` and `bot.expect()` work.
- Clean disconnect and kick handling with parsed reasons. Reconnect with backoff.

**Testing.**
- `testing/fake_server.py` scripts the whole handshake in CI: negotiating compression and encryption, Configuration, and Play login.
- State-machine tests: illegal transitions raise `StateError`.
- EventBus tests under `FakeClock`: ordering, waiter-before-listener, exception isolation, `expect` race freedom, no leaked tasks at close.
- Integration (marked, Docker): itzg/minecraft-server and Paper.

### M3: World State (Chunks, Blocks, Entities, Inventory)

**Scope.** `world`, `PalettedContainer` decode, block updates, chunk batches, dimension changes, entity tracker, bot state handlers (health, food, XP, gamemode, hotbar and window 0).

**Definition of Done**
- Decoded block state IDs for 100% of sampled blocks in recorded 1.20.4 chunk packets match prismarine-chunk golden output.
- Handles `chunk_batch_start/finished` and replies `chunk_batch_received`. Handles unload, `multi_block_change`, `block_change` and dimension switch (world cleared).
- `bot.world.block_at(...)`, `find_blocks`, `raycast` correct on golden fixtures.
- Memory: a 441-column world sits below an agreed budget. The `uniform-section = zero allocation` property is demonstrated.
- Entity spawn, move (relative and teleport), remove and metadata for players and mobs are tracked.

**Testing.**
- Golden fixtures produced by `tools/mineflayer_oracle` (Node) for chunk packets and expected states at sampled coordinates.
- Property tests: `with_set` then `get` consistency, bit packing at every `bits` 4–15, and non-spanning boundaries at `bits` that don't divide 64 (5, 6, 7, 9, 13, 15).
- Mutation-isolation tests: a snapshot is unchanged after later updates.
- Replay tests using `.pfr` recordings.

### M4: 20-TPS Physics & Anti-Cheat-Compliant Movement

**Scope.** `physics`, `TickDriver`, controls, collision, media, effects, movement packet emission, teleport confirmation, `look`, jump, sprint, sneak.

**Definition of Done**
- A drift-compensated 20 TPS loop. Tick jitter p99 < 5 ms on an idle loop, and catch-up never bursts more than 2 ticks.
- Differential test vs the Mineflayer oracle (prismarine-physics) over scripted input traces (walk, sprint-jump, ice, soul sand, water, lava, ladders, cobweb, honey, slime, stairs and step-up): position error ≤ 1e-6 per tick, and any divergence documented and justified against vanilla `LivingEntity.travel`.
- 10-minute run of a scripted walk course on vanilla and Paper with no "moved too quickly" or "moved wrongly" log lines and no setbacks. The only teleport confirmations are legitimate ones.
- Movement packet cadence matches vanilla: send position when the squared delta exceeds 4e-8 or on the 20-tick reminder, send rotation on change, and set the ground flag correctly.

**Testing.** Oracle traces, a deterministic engine under `FakeClock`, and fuzzed control sequences checking invariants (never inside solid blocks, `on_ground` consistency). A Docker server test scans the server log for movement warnings.

### M5: discord.py-Style Extension Layer

**Scope.** `ext.commands`, `ext.tasks`, cogs, extension loader with hot reload, converters, checks, flags, help, `ChatParser`, `ChatQueue`, cache-style accessors (`bot.players`, `bot.entities`, `bot.get_player`).

**Definition of Done**
- The DX north-star snippet works unchanged.
- 20 reload cycles of an extension with commands, listeners and loops leave zero leaked subscriptions, tasks or commands. A broken reload rolls back cleanly.
- Converters, `Greedy`, `Range`, flags, checks and cooldowns behave like their discord.py counterparts, with documented differences.
- `tasks.loop(ticks=...)` aligns to physics ticks.
- Outbound chat respects the rate limit, so a spam test causes no kicks.

**Testing.** FakeServer-driven chat scenarios, `FakeClock` for cooldowns and loops, a reload-leak harness using `gc` and task introspection, and a parser fuzz test (unbalanced quotes, unicode, `§` formatting).

### M6: A* Pathfinder & Action Framework

**Scope.** `pathfinder`, `actions` (scheduler, Dig, Place, Equip, Eat, Attack, Look, GoTo), `SurvivalMonitor`, window clicks and inventory transactions.

**Definition of Done**
- `goto(GoalNear(...))` over 100+ blocks of mixed terrain with no server setbacks. Supports traverse, diagonal, ascend, descend, controlled fall, ladder, and optionally scaffold or dig-through behind flags.
- A* never blocks the loop: p99 loop stall < 10 ms during a 50k-node search. It runs in an executor on a snapshot or is time-sliced.
- Replans when blocks change in the path.
- Preemption works end to end: a mining job is cancelled by the `SurvivalMonitor` (drowning, lava, low health), the escape runs, and the job resumes from its checkpoint.
- Dig timing matches vanilla (tool, enchant, effects, in-water and airborne penalties). Block place and dig use correct sequence numbers.

**Testing.** Pure-Python graph tests, golden path-cost tests vs the oracle where comparable, scheduler unit tests with property-based interleavings (no resource double-held, no deadlock, preempted cleanup always runs), and Docker scenario tests (escape lava, mine a tree, build a bridge).

### M7: Multi-Bot Swarm & Shared World

**Scope.** `swarm`: `BotCluster`, `SharedWorldRegistry`, staggered login, coordinator (claims, blackboard), shared planner cache, metrics, failure isolation.

**Definition of Done**
- 50 offline-mode bots on one Paper server within a documented RAM and CPU budget, with chunk memory approximately constant in N for co-located bots. Measure against N independent bots.
- Login stagger respects `connection-throttle`. One kicked bot doesn't affect the others, and per-bot reconnect works.
- Shared TickDriver keeps all bots under budget (tick processing for N bots < 50 ms, or it degrades gracefully by dropping the cluster to sharded tick groups and reporting it).
- The block-claim registry prevents two bots mining the same block. Cluster-level events and commands work.

**Testing.** Memory benchmark (`tracemalloc`/`pympler`) in CI against thresholds, a FakeServer with N synthetic clients for correctness, a chaos test (random kicks and packet drops), and a deadlock/livelock soak test.

### Risk register

1. **Version churn.** Mitigated by a feature-flag layer and golden fixtures per version.
2. **minecraft-data protocol gaps** for newer versions. Mitigated by native codecs and verifying each pinned SHA.
3. **Physics divergence.** Mitigated by oracle traces and vanilla source cross-checks.
4. **Chunk decode performance.** Mitigated by numpy and offloading, with a benchmark gate.
5. **Microsoft auth changes.** Mitigated by isolating it behind `AuthProvider` and supporting an injected token.
6. **Signed chat** (`enforce-secure-profile`). Explicitly deferred. Document the limitation in M2 and revisit after M7.

---

# PROMPTS.md

## Section 4: Mega-Prompts

**How to use.** For each session, paste `COMMON PREAMBLE` first, then the milestone prompt. Attach `ARCHITECTURE.md` and the Handoff Notes from the previous milestone. The preamble is stated once so the standards cannot drift between sessions. If your tooling requires fully standalone prompts, concatenate them with a small script.

### COMMON PREAMBLE

````text
ROLE
You are a senior Python systems engineer implementing one milestone of "PyFlayer" (working title),
an asyncio Minecraft Java Edition bot library (Mineflayer's protocol/world/physics + discord.py's
architecture). ARCHITECTURE.md is the source of truth. Do not rename or restructure anything it
defines. If it is ambiguous, choose the simplest interpretation consistent with its ADRs and list
your assumption under "Assumptions" at the end.

CODING STANDARDS (non-negotiable)
- Python 3.11+. Use asyncio.TaskGroup, asyncio.timeout, ExceptionGroup, typing.Self, enum.StrEnum.
- `from __future__ import annotations` in every module. Full type hints; must pass `mypy --strict`
  and `pyright` strict. No `Any` in public signatures (use TypeVar/Protocol/generics; `object` over Any).
- Value types are `@dataclass(frozen=True, slots=True)`. Mutable state classes use `__slots__`.
- ZERO blocking calls on the event loop: no time.sleep, requests, sync file/network I/O, or any
  synchronous step that can exceed ~2 ms (the loop budget is 50 ms/tick). Offload via
  `_internal.cpu.run_cpu` or `asyncio.to_thread`. zlib inflate of payloads > 64 KiB is offloaded.
- Cancellation safety: never swallow `asyncio.CancelledError`; cleanup in `finally`; use structured
  concurrency (TaskGroup) for owned tasks; every created task is tracked and cancelled on close;
  no fire-and-forget tasks without a retained reference.
- Time only through the injected `Clock`. No direct `time.monotonic()`/`asyncio.sleep` outside
  `_internal/clock.py`.
- Errors: only exceptions from `pyflayer.errors` (PyFlayerError tree). Never raise bare Exception or
  ValueError from library code. Include structured fields. No `assert` for runtime validation.
- Logging via `logging.getLogger("pyflayer.<module>")`. No print().
- Layering: obey the layer map and `.importlinter` contracts. No upward imports. Cross-layer calls
  go through Protocols in `models/protocols.py`. TYPE_CHECKING-only imports are allowed for
  annotations only.
- Public API: define `__all__`. Google-style docstrings on all public symbols with usage examples
  for non-trivial ones.
- Tests: pytest + pytest-asyncio (asyncio_mode=auto) + hypothesis. Deterministic: use FakeClock,
  no real sleeps, no network except tests marked `integration`.
- Tooling: ruff (lint+format), mypy, pyright, import-linter, coverage >= 90% on new code.

OUTPUT FORMAT
1. A file tree of everything you create or modify.
2. Each file in full, in its own fenced block with its path as the header.
3. Tests (full).
4. A "Definition of Done" checklist with each item marked verified/unverified and how.
5. "Assumptions" and "Known Limitations".
6. "HANDOFF NOTES" (<= 60 lines): public symbols added, invariants the next milestone may rely on,
   TODOs deliberately deferred, and exact commands to run the test suite.
Do not implement features outside this milestone's scope. Do not leave TODO stubs in required files.
````

### PROMPT M1: Transport, VarInt Framing, Data Loader, Codec Compiler

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md]

MILESTONE 1 of 7. No prior milestones exist. You are creating the repository foundation.

GOAL
Raw TCP transport with Minecraft framing, the minecraft-data loader, and a protodef codec compiler,
proven against real byte-level fixtures. No login flow yet (that is M2).

FILES TO GENERATE
Repo: pyproject.toml (hatchling, src layout, deps: numpy, msgspec, cryptography, httpx, dnspython;
dev: pytest, pytest-asyncio, hypothesis, ruff, mypy, pyright, import-linter), .importlinter (layer
contracts from ARCHITECTURE 1.1), .github/workflows/ci.yml (matrix 3.11/3.12/3.13), README stub,
tools/record_session.py (records raw frames to a .pfr file; may be minimal).
src/pyflayer/: __init__.py, py.typed, errors.py (full tree from ARCHITECTURE 1.3),
_internal/{clock.py, cpu.py, log.py, util.py}, models/{vec3.py, aabb.py, enums.py, text.py, items.py,
protocols.py}, data/{loader.py, schema.py, registries.py, shapes.py, features.py, versions.py},
protocol/{varint.py, buffer.py, types/{nbt.py, position.py, slot.py, uuid.py, bitset.py}, protodef.py,
registry.py, framing.py, crypto.py, connection.py, status.py}.
tests/: unit tests for each module, tests/golden/ fixtures, a loopback fake server helper.

REQUIREMENTS
Clock: Clock Protocol (monotonic(), async sleep(), async sleep_until()); MonotonicClock; FakeClock with
manual advance() that wakes sleepers deterministically in deadline order.
VarInt/VarLong: max 5/10 bytes, two's-complement negatives, reject over-long encodings (MalformedPacket),
streaming decode from an async reader and from memoryview.
PacketReader/Writer: memoryview-based, zero-copy slices; all primitives (u/i 8/16/32/64, f32/f64, bool,
VarInt/VarLong, string with max length 32767 UTF-16 code units, UUID, position (x:26,z:26,y:12 packed,
signed; note pre-1.14 ordering is different and feature-gated), byte arrays, BitSet, optional/array helpers.
NBT: both network form (nameless root since protocol 764 / 1.20.2) and named-root file form; all tag types;
depth limit; bounds checks; typed Python mapping (no silent coercion).
Slot: 1.20.4 layout (present, itemId, count, optional NBT). Leave a clearly-marked extension point for
structured components (1.20.5+) via native/ codecs; do not implement them.
Framing: [length VarInt][data length VarInt if compression on][packet id VarInt][payload]. Threshold -1 means
off. Data length 0 means this packet is uncompressed. Max compressed frame 2^21-1; max declared uncompressed
size 2^23 (reject larger BEFORE inflating; guard against zlib bombs using a bounded decompressobj).
Encryption: AES-128-CFB8 with key=iv=shared secret, independent encrypt/decrypt stream states, usable
mid-stream (enabled after the first encrypted frame boundary).
Connection: asyncio.open_connection with TCP_NODELAY, connect/read/write timeouts via asyncio.timeout,
SRV lookup (_minecraft._tcp.<host>) with fallback to host:25565, IPv4/IPv6, clean close semantics,
backpressure via drain(). Reader loop reads exactly one frame at a time (readexactly), tolerates 1-byte
fragmented reads.
Status: handshake + status request + ping, returning a typed ServerStatus (version, protocol, players,
description as ChatComponent, favicon bytes, latency). Handle servers that send malformed JSON gracefully.
Data loader: McData.load("1.20.4") via dataPaths.json in the vendored submodule path (configurable via
PYFLAYER_DATA_DIR); msgspec Structs; registries with by_name/by_id; block state-id tables;
ShapeTable indexed by state id; Features from features.json; lru_cache per (version, data_commit).
Protodef compiler: compile protocol.json (handshaking/status/login/configuration/play, both directions)
into codec closures at load. Support: varint, varlong, i8-i64, u8-u64, f32, f64, bool, UUID, pstring,
buffer, restBuffer, array (countType and count-by-field), container, switch (compareTo + default),
option, bitfield, bitflags, mapper, topBitSetTerminatedArray, nbt, optionalNbt, anonymousNbt, position, slot.
Registry: (version, state, direction) <-> packet id <-> name <-> codec. Unknown packet id => UnknownPacket
carrying the raw bytes (never fatal here; policy is M2's job). Provide an override mechanism for native codecs.

EDGE CASES TO HANDLE AND TEST
- VarInt 6th byte; negative VarInt (-1 encodes to ff ff ff ff 0f); VarInt split across TCP reads.
- Frame length 0; frame length > limit; compression enabled with data-length < threshold; data-length 0.
- Length of declared uncompressed data lying (smaller/larger than actual) => CompressionError.
- Strings: 3-byte UTF-8 BMP, surrogate pairs (4-byte), overlong => MalformedPacket; max-length boundaries.
- Trailing unread bytes in a decoded packet: configurable strict/lenient, default strict in tests.
- Position: negative coordinates, boundaries of 26/12-bit ranges.
- NBT: nameless root, empty lists with tag type 0, list of compounds, depth bomb, Modified-UTF8 vs UTF-8
  (document your choice).
- Server closes mid-frame => ConnectionClosed with bytes-consumed context.

TESTS
Hypothesis round-trips (VarInt/VarLong/strings/NBT/position/BitSet); golden vectors from documented
protocol examples; fuzz (truncation/bit flips => only MalformedPacket/ProtocolError family, never hang);
a loopback asyncio server that feeds adversarial 1-byte reads; AES-CFB8 interop test vs `cryptography`
reference; compression threshold boundary tests; data loader tests that assert exact counts for a few
registries and spot-check block state ids; compiler tests encoding/decoding every login/config packet.
An optional integration test (marked) pings a real server given an env var.

CONSTRAINTS / NON-GOALS
No login/auth, no packet-name-based dispatch, no events, no world. Do not hand-write packet classes for
protodef-covered packets: they must come from the schema.

DEFINITION OF DONE
(see ROADMAP M1) plus: import-linter passes with the full layer contracts present even though upper
layers are empty; `python -m pyflayer.protocol.status <host>` prints a status.
````

### PROMPT M2: State Machine, Auth, Event Bus, Minimal Bot

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1 HANDOFF NOTES]

MILESTONE 2 of 7. M1 provides: Clock, framing, crypto, Connection, protodef codecs, McData, errors.
Do not modify M1 public signatures; extend only.

GOAL
A bot that logs in (offline and Microsoft/online), completes Configuration, enters Play, stays alive,
chats, dies and respawns, disconnects cleanly, and reconnects, all observable through a typed event bus.

FILES TO GENERATE
protocol/{state.py, client.py, auth/{base.py, offline.py, microsoft.py, session_join.py}}
events/{base.py, bus.py, catalog.py}
bot/{__init__.py, bot.py, lifecycle.py, chat.py, handlers/{__init__.py, login.py, keepalive.py,
chat.py, health.py, disconnect.py, resourcepack.py}}
testing/fake_server.py (scriptable in-process server implementing handshake, optional encryption, compression,
login, Configuration, and a minimal Play login for 1.20.4)
tests/ for all of the above; docs/events.md.

REQUIREMENTS
ConnectionState enum + a transition table; illegal transitions raise StateError. State changes apply
at exact packet boundaries (compression/encryption/state switches happen after the triggering packet).
ProtocolClient: connect(), packets() -> AsyncIterator[Packet], send(), close(); owns one reader task and a
single writer lock (TaskGroup-owned); typed Packet(name, state, fields, raw_len).
Login flow: Handshake (protocol version from McData, SNI-less hostname exactly as used for connect/SRV
target per vanilla), Login Start (name + UUID required for 1.20.2+), handle Encryption Request: RSA-PKCS1v1.5
encrypt shared secret + verify token with the server DER public key; server hash = Minecraft-style signed
SHA-1 hexdigest of (server id + shared secret + public key); call sessionserver join (httpx, async);
enable AES-CFB8 both directions; handle Set Compression (threshold, including <0 disable) and Login Success;
for 1.20.2+, send Login Acknowledged and enter CONFIGURATION; handle Login Disconnect.
Configuration: send client_information (settings) and minecraft:brand plugin message; handle server
plugin messages, feature flags, registry data (parse dimension/biome registries needed later into
DimensionInfo: min_y, height, logical_height), tags, update_tags, ping/pong, keep-alive, resource-pack
prompts (policy: accept | decline | callback via bot option), cookie requests (answer "no cookie" for
1.20.5+ versions only when applicable), and finish_configuration -> send finish ack -> PLAY.
Play: handle server-initiated start_configuration (re-enter CONFIGURATION, ack, return to PLAY) without
losing the bot object. Keep-alive in BOTH configuration and play echoes the long id promptly (must be well
under the server's 30 s timeout; test the deadline). Handle login (join game) packet: entity id, hardcore,
dimension names, gamemode, dimension type/name, view distance, etc.; position (synchronize player position)
=> send teleport_confirm and defer the position_look echo hook for M4 (provide a documented stub event
TeleportRequestEvent).
Auth: AuthProvider Protocol -> Session(username, uuid, access_token|None). OfflineAuth: UUIDv3 from
"OfflinePlayer:<name>" (MD5, set version/variant bits). MicrosoftAuth: device-code flow -> Xbox Live ->
XSTS -> Minecraft services -> profile, httpx.AsyncClient, tokens cached to a user-supplied path via
asyncio.to_thread, refresh-token reuse, clear AuthError subclasses (no Xbox account, child account,
no game ownership, XSTS error codes mapped). Allow injecting a pre-obtained token.
EventBus: exactly the API in ARCHITECTURE 2.1 including expect()/wait_for/stream, per-listener tasks, error
isolation, priority >= 1000 inline internal hooks, owner-based unsubscribe, aclose().
Event catalog (frozen dataclasses): ConnectEvent, LoginEvent, ConfigurationStartEvent, SpawnEvent, RespawnEvent,
DeathEvent, HealthEvent, ChatEvent (with ChatMessage), KickedEvent(reason: ChatComponent), DisconnectEvent,
ErrorEvent, RawPacketEvent (opt-in), TeleportRequestEvent.
Bot: connect(), wait_until_ready(), close(), send_chat(), respawn(), properties: username, uuid,
health, food, game_mode, dimension; on_<event> decorator registration via bot.event; reconnect policy
(exponential backoff with jitter, max attempts, do-not-reconnect on AuthError/ban kicks).
ChatParser v1: normalizes system_chat, player_chat, disguised_chat, legacy chat into ChatMessage.
Outbound chat: send plain chat (unsigned) and commands; ChatQueue token bucket (1 msg/1.1 s, burst 3, split >256).
Document that servers with enforce-secure-profile reject unsigned chat (known limitation).

EDGE CASES TO HANDLE AND TEST
- Compression enabled mid-login, then threshold changed later in Play (rare but legal).
- Encryption Request with no online-mode ("offline" server) — no encryption packet; ensure no hang.
- Kick during Login/Configuration/Play: reason as JSON string (older) vs NBT component (1.20.3+).
- Server sends packets between our state switch and its acknowledgment (e.g. Play packets before we send
  Finish Configuration is not allowed, but reordering of ping/keep-alive and plugin messages is).
- Keep-alive arriving during Configuration; Ping/Pong in Play and Configuration.
- Duplicate or unknown packets in Play are skipped and counted, never fatal.
- Death with "show death screen" disabled; respawn via client_command(perform_respawn).
- Task leak: after close() no tasks remain (assert via asyncio.all_tasks()).
- Connection reset while writing; write after close raises ConnectionClosed, not AttributeError.

TESTS
FakeServer scenarios for each flow above (offline, online with mock sessionserver, compression on/off,
Configuration re-entry, kick variants, keep-alive timeout). EventBus tests using FakeClock. Property-based
test that a random interleaving of dispatch/subscribe/unsubscribe/wait_for never loses an event for an
active waiter. Integration (marked): itzg/minecraft-server 1.20.4 offline-mode, bot joins, says hello,
is killed via RCON, respawns.

CONSTRAINTS / NON-GOALS
No world/chunks, no physics, no movement packets besides the minimal teleport_confirm, no commands framework,
no signed chat. Unhandled Play packets are counted and dropped, not decoded eagerly (lazy decode via
registry on demand).

DEFINITION OF DONE
(see ROADMAP M2).
````

### PROMPT M3: World State (Chunks, Blocks, Entities, Inventory)

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1 and M2 HANDOFF NOTES]

MILESTONE 3 of 7. Available: working login/Play loop, EventBus, McData (blocks/shapes/biomes),
DimensionInfo (min_y, height), handlers framework in bot/handlers.

GOAL
An accurate, memory-efficient, copy-on-write world model and entity/inventory state kept in sync with
the server, with state updated BEFORE user listeners run (ADR-4).

FILES TO GENERATE
world/{palette.py, section.py, chunk.py, world.py, view.py, store.py, entities.py, block.py, raycast.py}
protocol/native/{chunk_data.py, block_entities.py, entity_metadata.py} (version-gated native codecs)
bot/handlers/{chunks.py, blocks.py, entities.py, inventory.py, player_state.py, dimension.py}
bot/inventory.py (Window 0 model, slot cache, held slot)
events/catalog.py additions: ChunkLoadEvent, ChunkUnloadEvent, BlockUpdateEvent, EntitySpawnEvent,
EntityMoveEvent, EntityGoneEvent, EntityMetadataEvent, InventoryChangedEvent, GameModeEvent,
ExperienceEvent, DimensionChangeEvent.
tools/mineflayer_oracle/ (Node scripts to emit chunk golden fixtures with prismarine-chunk)
tests/ (golden + property + replay), docs/world.md.

REQUIREMENTS
PalettedContainer per ARCHITECTURE 2.3: SINGLE/INDIRECT/DIRECT, COW with_set/with_sets, numpy-vectorized
decode, uint8/uint16 indices, zero allocation for uniform sections. Decode MUST implement:
 - 1.16+ NON-SPANNING packing: per_long = 64 // bits; entries never straddle longs; long count =
   ceil(N / per_long). Also implement the pre-1.16 spanning layout behind a Features gate, with tests.
 - Block bits: bits < 4 => 4 (indirect), 4..8 indirect, >= 9 direct with bits = ceil(log2(num block states)).
 - Biome bits: 0 single, 1..3 indirect, >= 4 direct with bits from biome registry size (4x4x4 cells).
 - Entry order YZX; longs big-endian; LSB-first within a long.
Chunk data packet (1.18+): x,z, heightmaps (anonymous NBT), data array sliced into N = height>>4 sections
(from DimensionInfo), block entities (packed xz, y, type, nbt), light data (parse and skip or store behind a
flag, never mis-advance the reader).
Chunk batches (1.20.2+): handle chunk_batch_start / chunk_batch_finished and REPLY with
chunk_batch_received (chunks-per-tick float, configurable default 20.0 / policy hook), otherwise the server
throttles or stalls chunk streaming. Handle unload_chunk, update_view_position, update_view_distance.
Block updates: block_change (position + VarInt state), multi_block_change (1.16.2+: section position packed
long x<<42|z<<20|y, entries VarLong stateId<<12 | (x<<8 | z<<4 | y) local coords), block_entity_data, and
acknowledge_player_digging sequence handling hooks (record only). Batch multi-changes into one COW section
copy. set_block_state returns False for no-ops and does not emit an event.
World API per 2.3 (WorldView/World, find_blocks with a spatial-iteration order starting nearest-first,
raycast DDA over collision/outline shapes, snapshot()). Block flyweights from the registry cache.
Dimension change (respawn / login with new dimension): atomically swap in a fresh World, emit
DimensionChangeEvent, preserve keep-attributes flags correctly (respawn data_kept bitmask).
ChunkStore with refcounting and WorldKey, BotWorldFacade (single-bot use now; designed for M7 sharing).
Entities: EntityTracker for spawn_entity / spawn_player (named player_info tracking: add/update/remove,
latency, game mode, listed flag; player UUID <-> name), entity position delta (relative short *4096 vs
legacy), teleport, head rotation, velocity, metadata (versioned entity-metadata codec; handle unknown
types safely), equipment, remove_entities (array), attach/passengers (record only), entity_effect/remove.
Own-player state: health/food/saturation, XP, gamemode (login + change_game_state reason codes), abilities.
Inventory: window 0 slots (set_slot, window_items with state_id), held-slot change, cursor item; keep
ItemStack immutable; do NOT implement clicking yet (M6) but record the latest state_id.
Caches: bot.players (dict by name/uuid), bot.entities, bot.world, bot.inventory as read-only views.

EDGE CASES TO HANDLE AND TEST
- Chunks arriving for the dimension we are leaving; duplicate loads of an already-loaded chunk (replace).
- Section with non_air count mismatch; light data lengths; sections count differing across dimensions.
- Negative chunk coordinates and negative world Y (min_y -64); bit-index math using floor-div and masks.
- Block updates for unloaded chunks are dropped silently (counted), not errors.
- Entity move packets for unknown entity ids; entity ids reused after remove.
- Large worlds: memory test — 441 columns decode must stay under a stated budget; benchmark must show
  decode time per column and that no single synchronous decode exceeds ~2 ms OR that it is chunked/offloaded
  per the CPU-budget rule.
- bits-per-entry values that do not divide 64 (5, 6, 7, 9, 13, 15): explicit tests at boundaries
  (last entry of each long, last entry of the array).
- Snapshot isolation: take snapshot, apply updates, snapshot unchanged; arrays are writeable=False.

TESTS
Golden: oracle-generated chunk packets + expected state ids at ~1000 sampled coordinates per fixture.
Property: PalettedContainer set/get/with_sets vs a plain dict model; encode(decode(x)) == x for fixtures.
Replay: .pfr recorded join of a flat world and of a void world with a few entities. Integration (marked):
real server; compare bot.world.block_at against a RCON `execute if block` oracle for random points.

CONSTRAINTS / NON-GOALS
No physics, no movement, no collision beyond what raycast needs. No pathfinding. No lighting queries
(parse-only). Do not mutate sections in place anywhere.

DEFINITION OF DONE
(see ROADMAP M3).
````

### PROMPT M4: 20-TPS Physics

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1-M3 HANDOFF NOTES]

MILESTONE 4 of 7. Available: World/WorldView with collision shapes (ShapeTable), block flyweights,
entities, health/gamemode state, TeleportRequestEvent stub, Clock/FakeClock.

GOAL
A deterministic vanilla-faithful player physics engine plus a drift-compensated 20 TPS driver that emits
anti-cheat-compliant movement packets and handles server teleports.

FILES TO GENERATE
physics/{tick.py, state.py, controls.py, engine.py, collision.py, media.py, attributes.py}
bot/handlers/movement.py (packet emission, teleport confirm/echo, velocity packets, ground flag)
bot/bot.py additions: look_at(), set_control(), controls handle, position/velocity/yaw/pitch/on_ground
events/catalog.py additions: PhysicsTickEvent, MovementCorrectedEvent (server setback), VelocityEvent
tools/mineflayer_oracle/physics_traces.js (scripted input traces -> JSON golden)
tests/ (oracle diff, invariants, driver timing), docs/physics.md.

REQUIREMENTS
TickDriver: target 50 ms; schedule next = prev_deadline + 0.05 (never now + 0.05); if behind by > 2 ticks,
run at most 2 catch-up ticks and drop the rest (log a warning + counter); expose tick counter, measured TPS,
jitter stats; cancel-safe; shared-driver capable (M7 will run many engines per driver). All time from Clock.
PhysicsEngine.step(state, controls, view) -> PlayerState: PURE and deterministic. Order of operations follows
vanilla LivingEntity.travel for the target version: input vector (x strafe, z forward) * 0.98 (sneak
multiplier 0.3), moveRelative with ground vs air acceleration (ground uses movement_speed * 0.21600002 /
(friction^3), air 0.02; sprint-jump horizontal boost 0.2; jump 0.42 + jump-boost effect), collide/move,
then vertical (gravity 0.08, drag 0.98) and horizontal friction (block friction * 0.91). Block friction/speed/
jump factors from data (ice, blue ice, slime, soul sand, honey). Media: water (swim/float, depth, dolphin's
grace out of scope), lava, ladders/vines/scaffolding climbing (sneak hold), cobweb/sweet berry/powder snow
slowdown, bubble columns (optional flag), slime-bounce, honey-slide, fall-damage-relevant state.
Collision: swept-AABB per vanilla (Y first, then the horizontal axis with the larger |delta| first),
0.6 step height with the vanilla recheck, sneaking edge-protection, entity collision OUT OF SCOPE.
Collision boxes from ShapeTable; unloaded chunk => treat as solid below/non-moving ("freeze until loaded"
policy, documented) to avoid falling through the void during chunk streaming.
Attributes/effects: speed, slowness, jump boost, levitation, slow falling; attribute modifiers from
update_attributes; sprint state rules (hunger > 6, not blinded, etc.), creative/spectator flying (basic
flying physics; flight abilities from player_abilities).
Packet emission (vanilla cadence): send position when sqr(delta) > 4.0e-8 OR position_reminder >= 20 ticks;
send rotation when changed; choose pos / pos_look / look / on_ground_only packet accordingly; correct on_ground
flag; send player_command (sprint start/stop, sneak) and input flags as the target version requires. Never
send more than one movement packet per tick.
Teleports: on server position packet (with relative-flags bitmask), apply absolute/relative values, send
teleport_confirm(id), then echo position_look with the corrected state on the next emission; reset velocity per
vanilla rules; emit MovementCorrectedEvent. Handle velocity (entity_velocity for self) and knockback.
Controls: ControlState with forward/back/left/right/jump/sprint/sneak; writes only via ControlHandle
(Lease integration arrives in M6; for now a single default owner, but the API must already be lease-shaped:
`controls = bot.controls.acquire(owner)` raising if already owned).
Look: smooth rotation limited per tick optional; sensitivity/GCD quantization of yaw/pitch (vanilla mouse
sensitivity granularity) so rotations look legitimate; wrap yaw to [-180,180).

EDGE CASES TO HANDLE AND TEST
- Standing in a block corner; walking off edges; jump under a one-block ceiling; stairs/slabs step-up;
  trapdoors, carpets, snow layers, fences (1.5 collision height), walls, pistons-ish shapes from data.
- 0.003 velocity threshold zeroing; negligible-movement snapping; floating-point determinism (use float64
  everywhere; no numpy for the scalar engine unless proven equal).
- Respawn / dimension change resets state; teleport during a jump; teleport request id reuse.
- Server "Moved wrongly"/"too quickly" are the failure signal; the integration test greps the server log.
- Stall: if the loop stalls 500 ms, the driver does not burst > 2 ticks (anti-"moved too quickly").
- Packet loss/reorder cannot occur over TCP but a late teleport can arrive between emission and tick: queue
  and apply at the next tick boundary.

TESTS
Oracle differential: for each scripted trace (walk, sprint, sprint-jump chain, ice, soul sand, honey, slime,
water entry/exit, lava, ladder up/down, cobweb, stairs, 1-block gap fall) per-tick position/velocity error
<= 1e-6; any allowed divergence is listed in docs/physics.md with a vanilla source reference. Invariant tests
(Hypothesis over random control sequences): never inside solid, on_ground consistent, speed bounded.
TickDriver timing under FakeClock (catch-up cap, drift compensation). Integration (marked, Docker Paper +
vanilla): a 10-minute scripted course produces zero movement warnings.

CONSTRAINTS / NON-GOALS
No pathfinding, no scheduler/leases, no vehicles/boats/elytra/riptide, no entity collisions, no mounting.
Do not call any server-side command to move the bot.

DEFINITION OF DONE
(see ROADMAP M4).
````

### PROMPT M5: discord.py-Style Extension Layer

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1-M4 HANDOFF NOTES]

MILESTONE 5 of 7. Available: Bot with events, ChatEvent/ChatMessage, ChatQueue, players/entities caches,
physics tick events. All ext code is a PURE CONSUMER of public Bot APIs (nothing below may import ext).

GOAL
A faithful discord.py-style framework: commands, cogs, converters, checks, flags, tasks.loop, hot-reloadable
extensions, help, with leak-free reload semantics.

FILES TO GENERATE
ext/__init__.py, ext/commands/{__init__.py, bot.py, cog.py, core.py, context.py, view.py, converters.py,
checks.py, flags.py, help.py, errors.py}, ext/tasks/{__init__.py, loop.py}
bot/ small additions only: bot.players/bot.get_player/bot.get_entity cache accessors, bot.wait_until_ready
(if not complete), ChatParser extensions (whisper regex sets, configurable)
examples/{basic_commands.py, cogs/miner.py, hot_reload.py}
tests/ (incl. a reload-leak harness), docs/ext.md and docs/migrating-from-discordpy.md.

REQUIREMENTS
Implement exactly the signatures in ARCHITECTURE 2.2 (Cog/CogMeta/listener, load/unload/reload_extension,
command/group/Command/Context, Converter protocol and built-ins, checks, cooldown/max_concurrency with
BucketType, Flag converters, tasks.loop with seconds/minutes/hours/ticks/time/count/reconnect).
commands.Bot(Bot): command_prefix (str | iterable | callable(bot, message) -> str|list[str], sync or async),
case_insensitive, strip_after_prefix, owner_ids (usernames/uuids), help_command, on_command / on_command_error /
on_command_completion events, process_commands(), get_context().
StringView: quoted strings (" ' and smart quotes optional), escapes, Greedy[T], consume-rest keyword-only
parameters, *args, Optional/Union fallbacks, Literal, Enum, Range[T, lo, hi], flags (--name value).
Converters built in: str,int,float,bool,Vec3,BlockPos (3 tokens, supports ~ relative to author or bot),
Player,Entity,Block,Item,Dimension,GameMode. Provide a `Converter` base class and `Annotated` support.
Checks: check(), is_owner, has_player_nearby, in_dimension, requires_idle (uses a stub Idle protocol that M6
satisfies; default True), cooldown, max_concurrency (with wait=True option). Error hierarchy per spec;
error handler chain: command.error -> cog_command_error -> bot.on_command_error -> logged.
Cog lifecycle: cog_load/cog_unload/cog_check/cog_before_invoke/cog_after_invoke/cog_command_error;
metaclass collects commands/listeners/loops. Per-cog state in `__cog_*__` tables.
Extensions: setup/teardown protocol; atomic reload with rollback; purge sys.modules for the extension
package subtree only; track everything an extension registered via owner tokens; unload cancels its loops,
unsubscribes listeners, removes commands and cogs.
tasks.loop: descriptor binding per cog instance; drift-compensated interval via Clock; ticks= mode keyed on
PhysicsTickEvent; before_loop/after_loop/error; start/stop/cancel/restart/change_interval/is_running/failed;
exception policy and add_exception_type; reconnect=True pauses across disconnects and resumes on ready.
Help: automatic !help listing commands/groups/cogs with brief/description/usage derived from signatures,
output paginated to chat-length limits and sent through ChatQueue as whispers when the invoker whispered.
Context.reply: replies by whisper if the command arrived by whisper (configurable), respects ChatQueue.
Security: commands from non-owners must never reach is_owner-protected commands; command parsing ignores the
bot's own messages and messages from the server ("system") unless explicitly enabled.

EDGE CASES TO HANDLE AND TEST
- Chat with formatting codes (§), Unicode, extremely long messages, empty args, unbalanced quotes,
  names with underscores, prefixes that are substrings of each other, case-insensitive aliases collision.
- Servers that rewrite chat as "<Player> msg" vs "[Rank] Player: msg" vs signed player_chat vs system chat
  that includes the sender: the ChatParser rules are data (regex list) and testable.
- Reload while a command is mid-execution (it finishes against the old code or is cancelled, per documented
  policy, never both); reload failing in setup, in teardown, or by syntax error; circular extension imports.
- Loop started in __init__ vs cog_load; loop exception inside before_loop; stop() during sleep; interval change
  mid-sleep; count loops; ticks-mode when the bot disconnects.
- Cooldown buckets for whispered vs public commands; multiple prefixes; case sensitivity; command name
  collision between cogs (CommandRegistrationError unless override).
- Converter that itself awaits an action (it must be cancellable and time-limited via timeout).

TESTS
FakeServer chat scenarios, FakeClock for cooldown/loop timing, the reload-leak harness (N=50 cycles; assert
bus subscription count, command count, task count and gc'd cog instances are flat), parser Hypothesis fuzz
(never raise anything but CommandError subclasses), a conformance matrix mapping every discord.py behaviour we
claim to match to a test ID, and the DX north-star example run end to end.

CONSTRAINTS / NON-GOALS
No pathfinder/actions (M6): requires_idle uses a stub. No slash-commands/interaction analog. No dynamic
code execution of user-supplied strings.

DEFINITION OF DONE
(see ROADMAP M5).
````

### PROMPT M6: A* Pathfinder & Action Framework

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1-M5 HANDOFF NOTES]

MILESTONE 6 of 7. Available: deterministic physics, ControlState with lease-shaped acquire, WorldView/
snapshot (COW), raycast, inventory state (read), ext layer (commands/tasks), events.

GOAL
(a) The ActionScheduler with Resource/Priority/Lease/preemption exactly per ARCHITECTURE 2.4; (b) an
asynchronous, non-blocking A* pathfinder and executor; (c) core actions (Dig, Place, Equip, Eat, Attack,
Look, GoTo); (d) SurvivalMonitor wired to the scheduler; (e) inventory click transactions.

FILES TO GENERATE
actions/{scheduler.py, base.py, dig.py, place.py, interact.py, equip.py, eat.py, attack.py, look.py,
goto.py, survival.py}
pathfinder/{goals.py, moves.py, costs.py, astar.py, planner.py, executor.py, cache.py}
bot/{inventory.py (window click transactions), handlers/{digging.py, interact.py, windows.py}}
models/protocols.py: finalize ActionHost
events/catalog.py additions: ActionStartedEvent, ActionFinishedEvent, ActionPreemptedEvent,
PathStartedEvent, PathUpdatedEvent, PathResetEvent, GoalReachedEvent
ext/commands/checks.py: wire requires_idle to the scheduler
tests/ (scheduler property tests, planner graph tests, scenario tests), docs/actions.md, docs/pathfinding.md.

REQUIREMENTS: SCHEDULER
Exactly the API and algorithm in 2.4: atomic all-or-nothing resource acquisition under a single lock;
strict-greater-priority preemption; cooperative cancellation using a PreemptToken cancel message; conversion
to ActionPreempted for awaiters; correct Task.uncancel() accounting so external cancellation is never lost;
lease.critical() deferral bounded by max_critical_s then forced revoke; OnPreempt policies ABORT/RESUME/
REQUEUE with checkpoint(); equal-priority queue with FIFO + aging; child() lease inheritance (no re-acquire);
Lease.controls writes raise LeaseRevoked after revoke and zero the controls the lease set; cancel_all(reason,
below) used by DeathEvent; metrics (preemptions, queue wait).
SurvivalMonitor: always-on, subscribes to health/air/fire/void/hunger signals and submits SURVIVAL actions
(Eat when food <= threshold and edible available; SwimUp when air low; LeaveFire / escape lava; AvoidVoid;
Flee when health low and attacker detected). Configurable and individually disable-able.

REQUIREMENTS: PATHFINDER
Goals: GoalBlock, GoalNear(pos, r), GoalXZ, GoalY, GoalGetToBlock, GoalFollow (dynamic, re-targets),
GoalCompositeAny/All, GoalInvert, GoalLookAt. Each: heuristic(node) admissible, is_end(node).
Moves (flag-gated set): traverse, diagonal, ascend (jump up 1), descend / controlled fall (<= max_drop with
safe-landing check, no water/lava/void/cactus/magma/fire/berry), climb (ladder/vine), swim (optional),
parkour (OFF by default), place-bridge and dig-through (OFF by default, cost-penalized, require tool/blocks).
Cost model in TICKS using the physics constants (walk ~4.633 ticks/block, sprint ~3.564, jump/fall costs from
the physics sim rather than guesses), penalties for liquids, cobwebs, honey, danger-adjacent blocks.
A*: open set heap with tie-breaking on h, node pool/arena to avoid allocation, closed set keyed by packed
int (x,y,z), best-effort partial path when search budget (nodes/time) is exhausted, optimistic goal-cost
heuristic weighting configurable. NEVER block the loop: run in run_cpu() on a WorldSnapshot with a node and
wall-clock budget, OR time-slice with await-yields every <= 3 ms; cancellation-aware.
Executor: follows the path through a Lease(MOVEMENT|LOOK); per-tick control writes; verifies progress by
position error against the expected node; detects stuck (no progress N ticks) -> replan; replans on
BlockUpdateEvent affecting path cells; handles door/trapdoor/gate interactions and jumping onto stairs; stops
exactly (anti-overshoot) at goal. Emits Path* events. Unloaded chunks ahead => plan to the loaded frontier then
extend ("incremental horizon").

REQUIREMENTS: ACTIONS
Dig: compute dig time from block hardness, best tool in hotbar (auto-equip via Equip), enchant (efficiency),
effects (haste/fatigue), and penalties (in-water without aqua affinity x5, not on ground x5); send
player_digging start/finish/cancel with the sequence counter (1.19+) and handle acknowledge_player_digging and
block_change confirmation; abort cleanly on preemption (send cancel digging in finally). Obey reach (<= 4.5 for
survival-like, per version), line-of-sight via raycast, look-at before dig with legit rotation.
Place: block_place with hand, position, face, cursor x/y/z, inside_block, sequence; choose reference block +
face; handle sneak requirement for interactable blocks; verify via block update.
Equip: hotbar vs inventory slot, uses window clicks with correct state_id + changed_slots + cursor item
(1.17.1+), validates against server-confirmed contents; handle click mismatches by resync.
Eat/Use item: use_item with sequence, hold-use ticks from data (food use duration 32), cancel on preempt.
Attack: look at target, cooldown-aware (attack strength ticker), reach checks. Look: smoothed/legit.
GoTo: Action wrapping Planner+Executor; resources MOVEMENT|LOOK; on_preempt=RESUME with checkpoint = goal.
bot.actions facade: run(), goto(), dig(), place(), equip(), eat(), attack(); `async with bot.actions.run(...)`.

EDGE CASES TO HANDLE AND TEST
- Two actions requesting overlapping resource sets in opposite orders concurrently => no deadlock.
- Preemptor arrives while the holder is inside lease.critical() / mid-packet-pair; preemptor arrives during the
  holder's own cleanup; cascade (SURVIVAL preempts COMBAT preempts WORK); resume order.
- Death during any action: everything cancelled, controls released, scheduler barrier until respawn.
- Path through a column that becomes lava/solid mid-path; goal inside solid block; goal unreachable (NoPath
  with best partial); start inside a block; world edge; unloaded destination.
- Dig: block replaced by another during dig; tool breaks; server cancels (ack with different state);
  gravity block (sand) falls onto the bot; liquid flows into the hole.
- Inventory click desync (server rejects), full inventory on pickup, offhand, cursor not empty.
- A* determinism (same input => same path) and tie-breaking; node budget exhaustion yields partial path.

TESTS
Scheduler: Hypothesis stateful model (random submit/cancel/preempt) asserting: resources never double-held,
no deadlock (all handles terminate), preempted cleanup always runs exactly once, no lost external
cancellations. Planner: synthetic worlds (corridors, stairs, caves, lava lakes) with golden paths and cost
checks vs the oracle where comparable. Loop-stall test: 50k-node search keeps p99 loop latency < 10 ms.
Scenario (marked, Docker): escape lava mid-mine and resume, chop a tree, cross a gap with bridge, eat when
hungry while pathing, no movement warnings in the server log.

CONSTRAINTS / NON-GOALS
No crafting UI, no villager trading, no building schematics, no elytra/boats, no swarm. Do not bypass the
scheduler (no action sends movement packets).

DEFINITION OF DONE
(see ROADMAP M6).
````

### PROMPT M7: Multi-Bot Swarm & Shared World

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1-M6 HANDOFF NOTES]

MILESTONE 7 of 7. Available: complete single-bot stack. ChunkStore + BotWorldFacade exist from M3 (designed
for sharing), TickDriver is shared-capable (M4), ActionScheduler per bot (M6).

GOAL
Run dozens of bots cheaply and safely: one copy of chunk data per (server, dimension), one shared tick driver,
staggered and throttle-aware logins, failure isolation, and lightweight cooperation primitives.

FILES TO GENERATE
swarm/{__init__.py, cluster.py, shared.py, stagger.py, coordinator.py, metrics.py}
bot/ minimal hooks: Bot(world_provider=..., tick_driver=..., http_client=...) injection points (backwards
compatible defaults)
ext/commands/ additions: ClusterBot/ClusterCog (optional) and cluster-level event decorators
examples/swarm_miners.py, benchmarks/{memory_swarm.py, tick_budget.py}
tests/ (FakeServer with N synthetic clients, chaos), docs/swarm.md.

REQUIREMENTS
BotCluster: async context manager; add_bot(auth, name=..., **options) / spawn(n, name_template); start(),
stop(), per-bot handles; broadcast(chat|command|callable); run_all(coro_factory); cluster events
(`@cluster.event async def on_bot_spawn(bot)`, on_bot_kicked, on_bot_reconnect); TaskGroup-based supervision
where one bot's exception NEVER cancels others (isolate with per-bot supervisor tasks; ExceptionGroups only
for cluster shutdown).
SharedWorldRegistry/ChunkStore per ARCHITECTURE 2.3: bots acquire/release chunk refs; first decode wins,
duplicates add a ref only (hash or version compare); block updates applied once (idempotent, source-tagged);
refcount GC on last release; dimension-switch rebinding; entity state stays per-bot with an optional
read-only SwarmEntityView. Prove invariants: a bot only reads chunks it currently references; mutating
operations happen only on the loop thread; snapshots stay immutable.
Shared TickDriver: one 20 TPS loop ticking all engines. Per-tick time budget accounting; if total tick cost
for N bots approaches 50 ms, degrade gracefully: stagger bots across sub-slots (tick groups) while preserving
each bot's own 50 ms cadence to the server, and expose metrics + a warning. Document the single-core ceiling
and the future sharding path (process-per-shard with chunk store replication) without implementing it.
LoginStaggerPolicy: configurable delay with jitter, honours connection-throttle (default 4000 ms per IP on
Spigot/Paper family), exponential backoff on "connection throttled" / "logging in too fast" kicks, global
concurrency limit for in-flight logins, shared httpx.AsyncClient for auth/session joins, Microsoft token
cache shared across bots, offline-mode name templating with uniqueness.
SwarmCoordinator: ClaimRegistry (claim/release BlockPos or regions with TTL and owner; auto-release on bot
death/disconnect/preemption), Blackboard (typed key/value with change events), role assignment, and a shared
PathCache keyed by (WorldKey, snapshot-version range, start/goal) with invalidation on block updates.
Failure isolation + recovery: per-bot reconnect with jittered backoff; a banned/kicked-permanently bot is
removed (policy configurable); cluster stays healthy.
Metrics: per-bot tps/latency/queue sizes, shared memory (chunks, sections, bytes), cache hit rates, exposed as
a dict and optional Prometheus-style text.

EDGE CASES TO HANDLE AND TEST
- 50 bots joining the same area simultaneously: duplicate chunk packets, many identical block updates.
- Bots in different dimensions or on different servers in one cluster (separate WorldKeys).
- A bot dies/kicks while holding claims, leases, or chunk refs: all released; no leaks (refcount returns to 0).
- Two bots race to claim the same block; claim expiry while the owner is mid-dig (owner must re-validate).
- Shared PathCache returning a path invalidated by another bot's block change; planner on a stale snapshot.
- Throttle kicks mid-stagger; auth server rate limiting (HTTP 429 with Retry-After).
- Cluster shutdown with bots in every connection state; cancel storms; no un-awaited tasks.
- Exception in a user cluster-event handler isolated from the cluster.

TESTS
Memory benchmark (tracemalloc/pympler): N co-located bots vs N independent bots; assert sublinear chunk memory
with a stated threshold, tracked in CI. Tick-budget benchmark for N in {10, 25, 50, 100} with FakeServer.
Chaos test (random kicks, random disconnects, slow reads); soak test for refcount/claim/lease leaks; Hypothesis
state machine for ChunkStore acquire/release/put/apply_block. Integration (marked): 50 offline bots on Paper,
cooperative mining with claims, measured RAM and CPU documented in docs/swarm.md.

CONSTRAINTS / NON-GOALS
No cross-process sharding, no distributed coordination across machines, no proxy/SOCKS support unless trivial
via an injectable connector. Do not break the single-bot API; every swarm feature is opt-in.

DEFINITION OF DONE
(see ROADMAP M7).
````

---

## Suggested workflow

1. Paste COMMON PREAMBLE + `ARCHITECTURE.md` + the milestone prompt into a fresh session.
2. Run the checks. Feed failures back in the same session.
3. Save the **HANDOFF NOTES** into `docs/handoff/M<n>.md` and attach them to the next session.
4. Before starting M3 and M4, generate the Mineflayer oracle fixtures (`tools/mineflayer_oracle/`). They are your ground truth, and the AI cannot verify its own physics or chunk decoding without them.

Two decisions are worth making before M1: the target-version policy (1.20.4 first, as I proposed), and whether `numpy` stays a hard dependency. I recommend keeping it hard, because a pure-Python fallback for paletted decode would double the surface area. I can expand any section into its final `.md` form, or tighten the prompts for a specific coding tool.