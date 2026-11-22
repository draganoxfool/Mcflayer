# Tasks

Living backlog. `[x]` means implemented **and** covered by the current test suite; `[~]` means
implemented but missing a roadmap gate (tooling, property tests, integration); `[ ]` means not
started. See [Sessions](sessions.md) for the narrative log.

## Completed: M1 (transport/data/codecs), M2 (login/auth/events/bot), M3 (world state), M4
(physics/movement), M5 (commands/tasks), M7 (swarm)

Reference target: **1.8.9 / protocol 47**. M3 is covered by the test suite and verified live on
PikaNetwork. **M4 is implemented and covered by the test suite:** deterministic physics, oracle
differential traces, bot-owned 20 TPS ticks, movement packet cadence, sprint/sneak actions and
teleport reconciliation. The live 10-minute vanilla/Paper anti-cheat soak has not been run here.
**M7 is implemented and covered by the test suite:** shared refcounted chunk stores/views, tick
groups, throttle-aware login staggering, cluster supervision, claims, blackboard, path cache and
metrics. M6 (pathfinder/actions) is still design-only; the 50-bot Paper soak and memory benchmark
have not been run here.

### Scaffolding and policy

- [x] `pyproject.toml` — hatchling, src layout, extras `[dev]`, pytest/ruff/mypy/pyright config.
- [x] `.importlinter` with the full layer contract (empty upper-layer packages included).
- [x] README and `.gitignore`.
- [x] Vendored `minecraft-data` subset for `pc/1.8` with a provenance notice.
- [x] Reference-version decision documented: **1.8.9**, feature-gated for newer versions.
- [x] GitHub Actions CI matrix (`3.11/3.12/3.13`).
- [~] Run `ruff`, `mypy --strict`, `pyright`, `import-linter` and record clean output.
- [~] Coverage ≥ 90% on new modules (configured; measure with `pytest --cov`).
- [ ] Add Hypothesis property tests for VarInt/VarLong/strings/NBT/position.
- [ ] Add `.github/workflows/docs.yml` for `mkdocs build --strict`.

### Errors / internal / models

- [x] Full `PyFlayerError` tree with structured fields.
- [x] `Clock` Protocol, `MonotonicClock`, deterministic `FakeClock` (deadline order, cancellation).
- [x] `run_cpu` thread offload helper with budget logging.
- [x] Logging helper; utilities (`ceil_log2`, `signed`, `clamp`, `batched`).
- [x] `Vec3`, `BlockPos`, `ChunkPos`, `SectionPos` (negative-coordinate safe).
- [x] `AABB`, enums, `ChatComponent`, `ItemStack`, cross-layer Protocols.

### Data

- [x] `McData.load` with `dataPaths.json`, `PYFLAYER_DATA_DIR`, caching.
- [x] msgspec schema structs and block/item/entity/biome/effect/food registries.
- [x] Legacy 1.8 block-state helper (`(id << 4) | meta`).
- [x] `ShapeTable` with metadata-indexed shapes.
- [x] `Features` flags + version/protocol mapping.
- [ ] Modern global block-state tables (`minStateId`/`maxStateId` ranges) — M3.
- [ ] Structured item-component registry — M2/M3.

### Protocol primitives

- [x] VarInt/VarLong encode/decode, signed negatives, over-long rejection, async streaming.
- [x] `PacketReader`/`PacketWriter`: all integers/floats/bool, VarInt, byte-counted UTF-8 strings,
      UUID, packed position, NBT, slot, BitSet, optional/array helpers, strict trailing check.
- [x] NBT all tags, named + nameless roots, depth/size limits, typed Python mapping.
- [x] Position layouts for pre-1.14 (XYZ) and 1.14+ (XZY), feature-gated.
- [x] Slot layouts for 1.8–1.12 and 1.13–1.20.4; 1.20.5+ raises with an extension point.
- [x] AES-128-CFB8 with independent stream states.
- [x] Framing with compression thresholds, bounded inflate, zlib-bomb rejection.
- [x] `Connection`: SRV, TCP_NODELAY, write lock, per-frame timeouts, encryption/compression hooks.
- [x] Server List Ping + CLI + typed status with graceful optional fields.

### Protodef / registry

- [x] Compiler: varint/varlong, ints/floats/bool, UUID, pstring, buffer/restBuffer, array
      (count type / count field / fixed), container, switch, option, bitfield, bitflags, mapper,
      void, NBT variants, position, slot.
- [x] Lazy compilation with caching, cycle detection, native overrides.
- [x] `PacketRegistry` with id↔name↔codec, `UnknownPacket` raw payload, strict/lenient decode.
- [x] 1.8.9 compile sweep: handshake/status/login 100%, play/toServer 100%, play/toClient 74/74.
- [x] Golden handshake bytes and round-trip tests for login/play packets.
- [x] Entity metadata codec (`protocol/native/entity_metadata.py`).
- [x] Native 1.8 chunk payload decoder (`protocol/native/chunk_data.py`).
- [x] Registry uses the native `ItemStack` slot codec rather than raw JSON container dicts.
- [ ] `topBitSetTerminatedArray` / `$compareTo` context switches — needed for newer versions.

### Documentation

- [x] MkDocs nav for architecture, roadmap, prompts, module reference, sessions, tasks.
- [x] One page per implemented layer: errors, models, internal, data, protocol, transport, protodef.
- [x] Discord.py-style API pages for physics, bot movement and the M4 event catalog.
- [x] `sessions.md`, `tasks.md` and handoff notes for M1–M4.
- [ ] Publish via `mkdocs gh-deploy` (optional, no account required).

## M2 — Login, state machine, auth, events, minimal bot (done, 0.5.0)

- [x] `ConnectionState` transition table; illegal transitions raise `StateError`.
- [x] `ProtocolClient`: handshake → login → play (configuration path reserved for 1.20.2+).
- [x] Offline auth (`OfflinePlayer:<name>` UUIDv3) and Microsoft device-code flow.
- [~] Live Microsoft login is untested (needs a real account); device code/XBL/XSTS code is in place.
- [x] Encryption request/response, sessionserver join, Java signed server hash.
- [x] Set Compression on/off mid-login.
- [x] Structured event bus (`wait_for`, `expect`, `stream`, owner unsubscribe).
- [x] `Bot` skeleton, keep-alive, chat I/O, kick parsing, respawn, reconnect backoff.
- [x] FakeServer for CI (offline + encryption + compression + kicks).
- [x] Document unsigned-chat limitation on `enforce-secure-profile` servers.
- [x] Live check: `python -m pyflayer.cli play.pika-network.net --username ...` joins and chats.
- [ ] Configuration state golden test once 1.20.2 data is vendored.
- [ ] Reconnect rate-limit/ban policy hardening (M7 hardening).

## M3 — World state (done, 0.6.0)

- [x] `PalettedContainer` (SINGLE/INDIRECT/DIRECT, COW, numpy vectorized, non-spanning).
- [x] `ChunkSection`, `ChunkColumn`, `World`, `WorldSnapshot`/`Bounds`, `ChunkStore` refcounts.
- [x] Chunk/block/entity/inventory handlers that mutate state before dispatch (ADR-4).
- [x] Native entity metadata and 1.8 chunk data codecs.
- [x] Legacy (`block<<4|meta`) state ids; `BlockState` names, properties and collision boxes.
- [x] Partial chunk merge, `multi_block_change`, `block_change`, dimension change and respawn clearing
      (`ChunkUnloadEvent` is reserved; 1.8 has no unload packet).
- [x] Entity spawn/move/look/teleport/velocity/metadata/equipment/attach/destroy tracking.
- [x] Window 0, `window_items`, `set_slot`, `held_item_slot`, open/close window, XP and attributes.
- [x] DDA raycast and `find_blocks` (name, state id or predicate).
- [x] Live Pika check: 25 chunks, 667 non-air blocks, 28 entities, block under spawn resolved.
- [ ] Modern global block-state tables (`minStateId`/`maxStateId` ranges) — data not vendored.
- [ ] Block-entity typed codecs (raw NBT is exposed today).
- [ ] Mineflayer oracle fixtures for chunk decode.
- [ ] Memory budget benchmark (441 columns).

## M4 — Physics and movement (implementation complete)

- [x] `PlayerState`, `ControlState`, player hitbox and material flags.
- [x] `PhysicsEngine.step()`: input acceleration, gravity/drag, friction, sprint/sneak, jump.
- [x] Swept AABB collision (Y/X/Z), full-hitbox translation, ground detection and 0.6 step-up.
- [x] Media pass: water/lava, ladders, cobwebs, ice/slime slipperiness, soul sand slowdown.
- [x] `TickDriver`: absolute 20 TPS deadlines, bounded catch-up, injected `Clock`, jitter/p99/TPS
      metrics and cancellation safety.
- [x] Differential oracle fixtures (`tools/mineflayer_oracle`, ten traces) with position error
      ≤ `1e-6` per tick against prismarine-physics 1.8.9.
- [x] Stairs, ladder climb/sneak hold, soul-sand slowdown and 300-tick fuzzed invariants in
      `tests/test_physics.py`; honey is 1.15+ and documented as deferred.
- [x] `examples/physics_demo.py`: slab step, sprint jump and wall stop with printed trajectory.
- [x] `MovementTracker` cadence: `4e-8` squared delta, rotation epsilon, ground flag and 20-tick
      reminder (`position`/`position_look`/`look`/`flying`), one packet per tick.
- [x] Teleport confirmation: `position_look` echo on 1.8, `teleport_confirm` on 1.9+, feature-gated.
- [x] `Bot` controls (`set_movement`, `stop_movement`, `look`, `jump`, `on_ground`) and bot-owned
      physics task with clean shutdown/reset.
- [x] `entity_action` `start/stop_sprinting` and `start/stop_sneaking` before movement changes.
- [x] `PhysicsTickEvent` after every completed tick.
- [x] Idle-loop measurement on this machine: 19.994 TPS, p99 jitter 0.83 ms, 0 drops (gate < 5 ms).
- [ ] 10-minute live anti-cheat run on vanilla/Paper (environment-dependent; no server here).

## M5 — Commands and tasks (done, 0.8.0)

- [x] `ext.commands.Bot`: optional prefixes plus address-based dispatch (whisper, name mention,
  `trigger=`, programmatic), `process_message`, `dispatch_command`.
- [x] `CommandPrefixError` (a `TypeError`) raised for `command_prefix=`; supported spelling is
  `prefix=` (str or collection), exposed as `ctx.prefix` when matched.
- [x] `Command`, `Group`, typed parameter parsing, positional/keyword-only/`*args`, `Greedy`, `Range`.
- [x] Built-in converters (`str`, `int`, `float`, `bool`, `Dimension`, `GameMode`, `Player`,
  `Literal`, `Optional`, `Union`, `Annotated`).
- [x] `Cog`, `CogMeta`, `listener`, lifecycle hooks, per-cog checks and error handling.
- [x] Checks, `check_any`, `cooldown` (player/global buckets), `max_concurrency`, `is_owner`,
  `in_dimension`, `has_player_nearby` — cooldowns on the injected `Clock`.
- [x] `FlagConverter` (`--name value` / `--name=value`), help command and `format_help`.
- [x] Extension `setup`/`teardown`, load/unload/reload with a per-extension ledger and atomic
  rollback; 20 reload cycles leak no subscriptions or commands.
- [x] `tasks.loop` on `seconds`/`minutes`/`hours` or `ticks`, with `count`, `before_loop`,
  `after_loop`, `error`, and cog-driven start/stop.
- [x] `examples/commands_demo.py` and `tests/test_commands.py` (23 tests).
- [x] Docs: module guides, API reference pages, migration guide, handoff.
- [ ] `tasks.loop(time=...)` scheduling and reconnect pausing (deferred).
- [ ] Loop/listener cost benchmark (not required by the gate that ran here).

## M7 — Multi-bot swarm and shared world (done, 0.9.0)

- [x] `Bot(world=..., tick_driver=...)` injection, `Bot.physics_tick()`, `Bot.closed`.
- [x] `SharedWorldRegistry` / `SharedWorld`: one refcounted `ChunkStore` per `(server, dimension)`,
      first-copy-wins decode, per-bot held set, refcount GC, dimension rebinding.
- [x] Idempotent shared block updates: only one bot emits `BlockUpdateEvent`; writes to chunks a bot
      does not hold are dropped.
- [x] `LoginStaggerPolicy`: minimum interval, jitter, concurrency cap, throttle-kick backoff on the
      injected clock.
- [x] `BotCluster`: add/spawn/remove, start/stop context manager, broadcast, run_all, per-bot
      supervision with failure isolation, reconnect backoff and kick policy.
- [x] Tick groups: round-robin `TickDriver`s at 20 TPS, p99 budget monitoring, automatic group
      addition up to `max_tick_groups`, `degraded` metric.
- [x] `ClaimRegistry` (blocks/regions, TTL, ownership, auto-release on death/disconnect), `Blackboard`
      with change events and `wait_for`, version-aware `PathCache`, `RoleRegistry`.
- [x] `ClusterMetrics` dict and Prometheus text (bots, shared chunks/bytes, tick timing, claims,
      cache hit/miss). Cluster events `on_bot_spawn`, `on_bot_kicked`, `on_bot_reconnect`,
      `on_bot_error`.
- [x] `tests/test_swarm.py` (12 tests): refcounts, view isolation, dimension rebinding, staggering,
      TTL claims, blackboard, LRU cache, three-bot FakeServer cluster, shared chunk/update, kick
      retirement and one-bot-closed isolation.
- [x] Docs: `modules/swarm.md`, `reference/swarm.md`, `handoff/M7.md`, `examples/swarm_miners.py`.
- [ ] 50-bot Paper soak, shared-memory benchmark and tick-budget benchmark (environment-dependent).
- [ ] Shared Microsoft token cache / injected `httpx.AsyncClient` (online auth remains untested).
- [ ] Chaos/soak leak tests and a real two-server cluster.

## M4–M7 (summary from the roadmap)

- [~] M4: implementation and test gates complete; the live vanilla/Paper anti-cheat soak remains.
- [x] M5: discord.py-inspired `ext.commands` / `ext.tasks` with **no** `command_prefix`, atomic
      extension reload, help, converters, checks, cooldowns.
- [ ] M6: action scheduler with leases/preemption, non-blocking A*, executor, Dig/Place/Equip/Eat/
      Attack/Look/GoTo, SurvivalMonitor, inventory transactions.
- [~] M7: `BotCluster`, shared `ChunkStore`, staggered logins, shared tick groups, claims and
      metrics are implemented; the live 50-bot soak and benchmarks remain.


## Known limitations (current code)

- 1.8.9 has no global block-state ids; modern state tables are not vendored, so `World` resolves
  legacy ids only (the `PalettedContainer` decoder itself supports modern layouts).
- Only 1.8 chunk data is decoded; the 1.20.2+ chunk-batch flow is not implemented.
- Microsoft auth is implemented but not exercised against a live account.
- Chat is unsigned; 1.19.1+ `enforce-secure-profile` servers will reject it when they are supported.
- Light data is stored but not recomputed client-side.
- Physics is bot-owned and packet-emitting; pathfinding remains M6+. Effects, attributes, flight
  and elytra are not fed into the engine, and server velocity packets for the local player are not
  applied.
- The 10-minute anti-cheat soak against vanilla/Paper has not been executed here.
- The bot pauses physics while its current chunk is unloaded instead of falling through terrain.
- The protocol compiler treats unknown **mapper** values as raw integers and unknown **types** as
  hard `UnsupportedType` errors (never silent corruption).
- `FakeClock.advance()` wakes sleepers but does not run tasks; use `advance_async()`.
- M6 is not implemented, so swarm claims, roles and the path cache are primitives for callers;
  no action scheduler consumes them and no planner fills the cache.
- The M7 50-bot Paper soak, shared-memory benchmark and tick-budget benchmark were not run here.
- Cluster auth is per bot; Microsoft tokens and the HTTP client are not shared across the swarm.
- The SLP CLI prints to stdout (the one allowed non-library `print`).

## Commands

```bash
# project
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# tests
pytest -q
pytest --cov=pyflayer --cov-report=term-missing

# quality
ruff check src tests
ruff format --check src tests
mypy
pyright
lint-imports

# docs
pip install -r requirements-docs.txt
mkdocs serve
mkdocs build --strict

# regenerate the physics oracle (Node; node_modules is ignored)
cd tools/mineflayer_oracle && npm install && npm run generate && cd ../..

# quick server ping
python -m pyflayer.protocol.status play.example.org

# join a server (1.8.9, offline auth) and print chat
python -m pyflayer.cli play.pika-network.net --username PyFlayerProbe --timeout 10 --chat hello
```
