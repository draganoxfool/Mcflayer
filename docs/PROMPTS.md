# Prompts

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

discord.py is an INSPIRATION for ergonomics, not a compatibility target: copy the patterns that make
bots pleasant to write (decorators, cogs, listeners, loops, typed dispatch) and drop everything that
has no meaning in Minecraft (prefixes, slash commands, interactions, permission hierarchies). We are
not porting it and we are not chasing feature parity.

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
- Hot paths (paletted decode, NBT, framing, A*) must have an optional accelerated path; see
  ARCHITECTURE "Performance & native acceleration". Pure-Python correctness first, native second,
  and only behind a flag-free import fallback that passes the same golden tests.

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
Golden: oracle-generated chunk packets and expected state ids at ~1000 sampled coordinates per fixture.
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

### PROMPT M5: Command & Extension Layer (discord.py-inspired)

````text
[PREPEND COMMON PREAMBLE + ARCHITECTURE.md + M1-M4 HANDOFF NOTES]

MILESTONE 5 of 7. Available: Bot with events, ChatEvent/ChatMessage, ChatQueue, players/entities caches,
physics tick events. All ext code is a PURE CONSUMER of public Bot APIs (nothing below may import ext).

GOAL
A command/extension layer with discord.py's ergonomics — decorators, cogs, listeners, converters, checks,
flags, tasks.loop, hot-reloadable extensions, generated help — for Minecraft chat. NOT a port: no
command_prefix, no slash commands, no interactions, no permission hierarchy, no feature parity. Keep it
small, obvious and OOP. Only concepts that make a Minecraft bot easier to write belong here.

FILES TO GENERATE
ext/__init__.py, ext/commands/{__init__.py, bot.py, cog.py, core.py, context.py, view.py, converters.py,
checks.py, flags.py, help.py, errors.py}, ext/tasks/{__init__.py, loop.py}
bot/ small additions only: bot.players/bot.get_player/bot.get_entity cache accessors, bot.wait_until_ready
(if not complete), ChatParser extensions (whisper regex sets, configurable)
examples/{basic_commands.py, cogs/miner.py, hot_reload.py}
tests/ (incl. a reload-leak harness), docs/ext.md, docs/migrating-from-discordpy.md.

REQUIREMENTS
commands.Bot(Bot) — NO command_prefix. Commands are dispatched only when a chat message is addressed to the
bot: a whisper (/msg <bot>) always counts, a mention of the bot's name counts, and an optional
`trigger: str | re.Pattern | callable` can be supplied for servers that rewrite chat. `bot.process_message()`
is the entry point fed by ChatEvent; `bot.dispatch_command(str)` is the programmatic path (tests, cogs,
REPL). Settings: case_insensitive, owner_ids, help, on_command/on_command_error/on_command_completion.
If a user writes `command_prefix=` in a ported snippet, raise a clear TypeError saying it was removed by
design — do not silently accept it.
Implement exactly the signatures in ARCHITECTURE 2.2 (Cog/CogMeta/listener, load/unload/reload_extension,
command/group/Command/Context, Converter protocol and built-ins, checks, cooldown/max_concurrency with
BucketType, Flag converters, tasks.loop with seconds/minutes/hours/ticks/time/count/reconnect).
Scope discipline: implement what ARCHITECTURE 2.2 lists and nothing more. Deferred on purpose: hybrid/slash
commands, app_commands, interactions, views/modals/buttons, permissions and roles, threads, webhooks.
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
Help: automatic "help" listing commands/groups/cogs with brief/description/usage derived from signatures,
output paginated to chat-length limits and sent through ChatQueue as whispers when the invoker whispered.
Context.reply: replies by whisper if the command arrived by whisper (configurable), respects ChatQueue.
Security: commands from non-owners must never reach is_owner-protected commands; command parsing ignores the
bot's own messages and messages from the server ("system") unless explicitly enabled.

PERFORMANCE
Command dispatch must not add measurable loop cost: parse on demand, no regex compilation at call time
(cache compiled patterns), no per-message allocations beyond the Context. A `!`-free design means no prefix
scan of every message: the addressed-check is a cheap substring/mention test and bails before parsing.
Keep the ext layer import-light: importing pyflayer.ext must not pull in numpy, physics or the planner.

EDGE CASES TO HANDLE AND TEST
- Chat with formatting codes (§), Unicode, extremely long messages, empty args, unbalanced quotes,
  names with underscores, case-insensitive aliases collision, a mention of a player whose name contains
  the bot's name as a substring.
- Servers that rewrite chat as "<Player> msg" vs "[Rank] Player: msg" vs signed player_chat vs system chat
  that includes the sender: the ChatParser rules are data (regex list) and testable.
- Reload while a command is mid-execution (it finishes against the old code or is cancelled, per documented
  policy, never both); reload failing in setup, in teardown, or by syntax error; circular extension imports.
- Loop started in __init__ vs cog_load; loop exception inside before_loop; stop() during sleep; interval change
  mid-sleep; count loops; ticks-mode when the bot disconnects.
- Cooldown buckets for whispered vs public commands; command name collision between cogs
  (CommandRegistrationError unless override); duplicate dispatch of the same message (idempotent handling).
- Converter that itself awaits an action (it must be cancellable and time-limited via timeout).

TESTS
FakeServer chat scenarios, FakeClock for cooldown/loop timing, the reload-leak harness (N=50 cycles; assert
bus subscription count, command count, task count and gc'd cog instances are flat), parser Hypothesis fuzz
(never raise anything but CommandError subclasses), a behaviour matrix mapping every discord.py behaviour we
deliberately keep to a test ID (and every one we drop to a line in docs/migrating-from-discordpy.md), and the
DX north-star example run end to end.

CONSTRAINTS / NON-GOALS
No command_prefix (by design, not an oversight). No pathfinder/actions (M6): requires_idle uses a stub. No
slash-commands/interaction analog. No dynamic code execution of user-supplied strings.

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
