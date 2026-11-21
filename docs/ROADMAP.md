# Roadmap

Milestone plan with definition-of-done gates. Architecture contracts live in
[Architecture](ARCHITECTURE.md); the session prompts live in [Prompts](PROMPTS.md).

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

### M5: Command & Extension Layer (discord.py-inspired)

**Scope.** `ext.commands`, `ext.tasks`, cogs, extension loader with hot reload, converters, checks, flags, help, `ChatParser`, `ChatQueue`, cache-style accessors (`bot.players`, `bot.entities`, `bot.get_player`).

**Design boundary.** Familiar ergonomics, not parity. No `command_prefix` (dispatch is address-based), no slash commands or interactions, no permissions/roles, no `Client`/`Bot` split. Only concepts with a Minecraft meaning are implemented; the migration guide records what was dropped and why.

**Definition of Done**
- The DX north-star snippet works, with commands addressed to the bot by whisper or name mention.
- `commands.Bot(command_prefix=...)` raises `CommandPrefixError` (a `TypeError`) with a message explaining the removal. No prefixed parsing path exists in the codebase.
- 20 reload cycles of an extension with commands, listeners and loops leave zero leaked subscriptions, tasks or commands. A broken reload rolls back cleanly.
- Converters, `Greedy`, `Range`, flags, checks and cooldowns behave like their discord.py counterparts, with documented differences; the deferred discord.py surface is documented rather than stubbed.
- `tasks.loop(ticks=...)` aligns to physics ticks.
- Importing `pyflayer.ext` pulls in no numpy, physics or planner modules, and dispatch adds no measurable per-message loop cost.
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
