# Sessions

One entry per implementation session. Newest last. This is the running log the roadmap asks for;
the structured backlog lives in [Tasks](tasks.md).

## Session 1 — 2026-11-20 — M1 foundation, targeting 1.8.9

**Prompt.** Read the design docs and create the first milestone module. Target 1.8.9 if that is
easier; otherwise go to a higher version directly. Use MkDocs for all module documentation. Record
what was implemented in `sessions.md` and the backlog in `tasks.md`.

**Target decision.** The reference version is **Minecraft 1.8.9 / protocol 47**.

Why 1.8.9 was accepted even though the architecture names 1.20.4:

- M1 is transport/data/codec work. 1.8.9's status and login flows are the simplest real target, and
  its data is a small vendored subset (≈300 KB vs several MB).
- There is no Configuration state, no registry-code packet, and no structured item components, so
  M1 can be end-to-end complete instead of half-built.
- The codec compiler is schema-driven, so the same code works for newer versions once their data is
  added. Version differences are feature-gated, not hard-coded.

Trade-offs recorded:

- 1.8.9 predates global block-state ids; block state ids are `(block_id << 4) | metadata`. M3 must
  add the modern state table.
- 1.8.9's network NBT has a named root; 1.20.2+ is nameless. Both are implemented.
- 1.8.9 has no Configuration state, so M2 is smaller than the architecture describes.

**Implemented**

- Project scaffolding: `pyproject.toml` (hatchling, src layout, extras), `.importlinter` with the
  full layer contract, `.gitignore`, README.
- `errors`: complete `PyFlayerError` tree with structured fields.
- `_internal`: `Clock` / `MonotonicClock` / deterministic `FakeClock`, `run_cpu`, logging helper,
  utilities.
- `models`: `Vec3`, `BlockPos`, `ChunkPos`, `SectionPos`, `AABB`, enums, `ChatComponent`,
  `ItemStack`, cross-layer Protocols.
- `data`: `McData` loader (cached, `PYFLAYER_DATA_DIR`), msgspec schema structs, six registries,
  legacy state helpers, `ShapeTable`, `Features`, version mapping.
- Vendored `data/pc/1.8` (blocks, items, entities, biomes, effects, foods, materials, windows,
  collision shapes, protocol, version) with a provenance notice.
- `protocol`: VarInt/VarLong, `PacketReader`/`PacketWriter`, NBT (named + nameless), position, slot,
  UUID, BitSet.
- Framing with compression thresholds, bounded inflate and zlib-bomb rejection.
- AES-128-CFB8 with independent directions.
- `Connection` with SRV, TCP_NODELAY, write lock, frame encryption/compression and timeouts.
- Server List Ping (`ping`, CLI, typed `ServerStatus`).
- Protodef compiler and `PacketRegistry`; all handshake/status/login packets and all play/toServer
  packets compile for 1.8.9. Four play/toClient packets are deferred because they need the entity
  metadata codec (M3).
- 96 tests covering golden bytes, Hypothesis-free edge cases, fuzz-style truncation/bit errors,
  loopback transport and an SLP round trip.

**Verification**

```bash
source .venv/bin/activate
python -m pytest -q                 # 96 passed
python -m pyflayer.protocol.status <host>   # SLP CLI
```

`ruff`, `mypy --strict`, `pyright` and `import-linter` are configured but were **not** installed in
this environment (PyPI resolution failed for `ruff` on Python 3.14). Run them before merging; see
[Tasks](tasks.md).

**Not done (deliberately out of M1 scope)**

- Login encryption handshake, auth, state machine, events, bot (M2).
- Native entity metadata / chunk codecs (M3).
- Modern block-state tables (M3).
- Hypothesis property tests were not written; the environment installed Hypothesis only late.
  The current suite is deterministic unit + loopback; add property tests before calling M1 “done”
  by the roadmap gate.

**Environment notes**

- Python 3.14 venv at `.venv`; docs venv at `.venv-docs`.
- `numpy`, `msgspec`, `cryptography`, `httpx`, `dnspython`, `pytest`, `pytest-asyncio`, `hypothesis`
  installed. `ruff`, `mypy`, `pyright`, `import-linter` are not (install once package resolution is
  reliable for 3.14 or use a 3.11/3.12 venv, which the CI matrix targets).

## Session 2 — 2026-11-20 — M2 login, auth, events, minimal bot (PikaNetwork working)

**Prompt.** Continue from M1. Read the design docs, keep writing `sessions.md`, and make the library
connect to `play.pika-network.net`; prepare the package for a PyPI upload afterwards. Open-source
data may be fetched if needed (none was needed: the vendored `pc/1.8` subset covers protocol 47).

**Target decision.** M2 is implemented against **Minecraft 1.8.9 / protocol 47** and validated live
against PikaNetwork, which is an offline-mode ("cracked") Velocity network that advertises protocol
47 and accepts 1.8 clients. The configuration-state code path exists but is not reachable with 1.8
data (there is no `configuration` state in `protocol.json`).

**Implemented**

- `protocol/state.py`: `ConnectionState` (moved into `models.enums`, now with `configuration` and
  `closed`) plus `StateMachine` with an explicit legal-transition table. Illegal transitions raise
  `StateError` with `current`/`target` fields; `closed` is terminal.
- `protocol/auth/`:
  - `base.py` — `Session`, `AuthProvider` Protocol, `StaticAuth` for injected tokens.
  - `offline.py` — username validation and vanilla-compatible UUIDv3
    (`OfflinePlayer:<name>`, version/variant bits set).
  - `session_join.py` — Java-compatible signed SHA-1 server hash and
    `sessionserver.mojang.com/session/minecraft/join` with `httpx`.
  - `microsoft.py` — device-code OAuth → XBL → XSTS → `login_with_xbox` → profile, with
    refresh-token reuse, injected `Clock`, pending/slow_down polling and mapped `AuthError`s.
- `protocol/client.py`: `ProtocolClient` — handshake, Login Start, Encryption Request (RSA
  PKCS#1 v1.5 secret/token, session join before the encrypted response, AES-CFB8 at the next frame),
  Set Compression, Login Success, Play packet iterator, unknown/unsupported play packets skipped and
  counted, chat/keep-alive senders.
- `events/`: typed `Event` base (`ChatEvent` → `on_chat`), frozen catalog (connect/login/join/spawn/
  respawn/death/health/chat/player-info/kick/disconnect/error) and the full `EventBus`
  (`subscribe` with priority/once/owner, `dispatch` with inline priority ≥ 1000 hooks, tracked
  listener tasks, waiter-first resolution, `wait_for`, race-free `expect`, bounded `stream`,
  `unsubscribe_owner`, `aclose`).
- `bot/`: `Bot` composition root (connect → wait for Join Game, client settings, keep-alive echo,
  chat parse/emit, health/food, death → auto `client_command(perform_respawn)`, respawn, kick
  parsing into `KickedError`, tab-list tracking, reconnect with backoff, `@bot.event`); `ChatQueue`
  token bucket (1.1 s / burst 3 / 256-char split); `parse_chat_json` unwraps `chat.type.text` and
  whisper/action-bar positions. `bot/chat.py`.
- `testing/fake_server.py`: in-process 1.8.9 server with optional RSA/AES encryption, compression,
  Join Game, keep-alive echo, chat echo, respawn and kicks — no Docker/network needed.
- `cli.py`: `pyflayer-connect` (and `python -m pyflayer.cli`) to join a server, print chat/spawn/kick
  and optionally send one chat line; `pyflayer-status` unchanged.
- Fixed the protodef compiler's parent-context switch (`../action`), which was needed to decode the
  1.8 `player_info` packet. Fixed a wrong UTF-8 length expectation in an M1 test.
- Packaging for PyPI: wheel/sdist now bundle the vendored `data` tree as `pyflayer/_data`, and the
  loader prefers it inside an installed wheel; version bumped to 0.5.0.

**Live verification**

```bash
source .venv/bin/activate
python -m pytest -q          # 134 passed
python -m pyflayer.protocol.status play.pika-network.net
python -m pyflayer.cli play.pika-network.net --username PyFlayerProbe --timeout 10 --chat hello
```

Observed output:

```
joined play.pika-network.net as PyFlayerProbe (entity 42794, gamemode 0, dimension 0)
spawned at (0.5, 70.0, 500.3)
[chat] (!) Please log in first: /login <password> (new here? /register ...)
[system] PikaNetwork » Please register with /register <password> <password>
```

Compression was negotiated at threshold 256, the login completed, Join Game/Spawn arrived and chat
round-tripped. The bot deliberately stays 1.8.9-only for now; Pika also accepts newer versions, but
the vendored data and codecs are 1.8.

**Known limitations (M2)**

- No world/chunk/entity state yet: `map_chunk*`, `entity_metadata` and three other play/toClient
  packets are counted and skipped (M3). The bot tracks its own position/health/players only.
- Online mode (Microsoft) is implemented but not exercised live — it needs a real account.
- Chat is unsigned (1.8 has no signing). Servers with `enforce-secure-profile` are irrelevant for
  1.8 but will reject unsigned chat on 1.19.1+ when those versions are added.
- Reconnect is a simple exponential backoff without a persistent rate-limit policy; Pika asks for
  `/login` or `/register` after join and that is left to the caller (see the CLI `--chat` flag).
- `ruff`/`mypy`/`pyright`/`import-linter` are still not installed in this Python 3.14 environment;
  the test suite is the verification gate that ran here.

**Version.** `0.5.0` — M1 + M2 complete enough to log into a real server. Not 1.0: world, physics,
commands, pathfinding and swarm are still M3–M7.

**Release.** `pyflayer` is taken on PyPI (upload returned 403 for the token owner), so the
distribution name is **`mcflayer`** while the import package stays `pyflayer`. `mcflayer 0.5.0`
(wheel + sdist) was uploaded to PyPI and verified with `pip download` + `importlib.metadata`
(`dist 0.5.0`, `import pyflayer` → protocol 47).

## Session 3 — 2026-11-20 — M3 world state

**Prompt.** Read the M3 handoff and related design docs, then complete M3.

**Implemented**

- `protocol/native/entity_metadata.py`: `EntityMetadataLoopCodec` for 1.8's terminator (`0x7F`) array,
  including metadata value types used by spawn/metadata packets. This completes the play state:
  **74/74 play/toClient and 26/26 play/toServer packets compile** for 1.8.9.
- `protocol/native/chunk_data.py`: `decode_legacy_chunk` / `LegacyChunkData` — block states
  (`uint16`), block light and sky light nibbles, biomes, block entities, and ground-up vs partial
  (`groundUp=False`) merging.
- `world/palette.py`: `PalettedContainer` with `SINGLE`/`INDIRECT`/`DIRECT` kinds, copy-on-write,
  numpy-backed reads, non-spanning and spanning modern unpacking, plus `from_legacy`.
- `world/section.py` / `chunk.py`: immutable `ChunkSection` (YZX, light) and `ChunkColumn`
  (sections, biomes, block entities, `version`, copy-on-write `with_block`).
- `world/world.py` / `view.py`: mutable `World` per dimension (apply/unload chunk, block reads and
  writes, `multi_block_change`, `find_blocks`, `raycast`, `snapshot`) and immutable
  `WorldSnapshot`/`Bounds` for worker threads.
- `world/block.py`, `raycast.py`, `store.py`: `BlockState` resolution and collision boxes, DDA voxel
  raycast, refcounted `ChunkStore` for the future bot cluster.
- `world/entities.py`: `Entity`/`EntityTracker` with relative move (1/32), look, teleport, velocity,
  metadata, equipment, attach/leash and name lookup by UUID.
- `bot/inventory.py`: window 0 and container windows, `window_items`/`set_slot`/`held_item_slot`,
  open/close window, hotbar selection and `held_item`.
- `bot/bot.py`: `world`, `entities`, `inventory`, `experience`, `attributes`; handlers for chunk,
  chunk bulk, block/multi-block change, all entity packets, inventory, XP and attributes. State is
  mutated before events are dispatched (ADR-4).
- New events: chunk load/unload, block update, entity spawn/move/gone/metadata, inventory changed,
  dimension change, experience.
- Tests: `test_palette.py`, `test_chunk_world.py`, `test_entities.py`, `test_inventory.py`,
  `test_metadata.py`, `test_bot_world.py`; the two M1 tests that asserted `entityMetadataLoop` was
  unsupported now assert the whole play state compiles.

**Bug found and fixed.** `tests/test_bot_world.py` hung after the entity step. The JSON schema's
`slot` container decoded to `{"blockId": ..., "itemCount": ...}` and encoding `ItemStack` raised
`TypeError` inside a detached `FakeServer` task, so the packet was never sent and the test waited
forever. The compiler now routes the `slot` type to the native `ItemStack` codec for 1.8–1.20.4.

**Live verification**

```bash
source .venv/bin/activate
python -m pytest -q          # 170 passed
python -m pyflayer.cli play.pika-network.net --username PyFlayerProbe --timeout 10 --chat hello
```

An M3 probe subscribed to `on_chunk_load`, `on_entity_spawn` and `on_block_update` and observed 25
chunks, 667 non-air blocks and 28 entities; the block under spawn was `emerald_block` and the bot
position `Vec3(0.47, 70.0, 500.26)`.

**Known limitations (M3)**

- Only 1.8.9 data is vendored, so `World` resolves legacy `(id << 4) | meta` state ids. The modern
  `PalettedContainer` decode path exists and is unit-tested but no modern chunk data is bundled.
- Chunk batches (1.20.2+), typed block entities, client-side lighting and physics remain future work.
- Entity metadata keys/values are exposed as decoded raw values, not typed per-entity classes.
- No Mineflayer oracle fixtures or 441-column memory benchmark yet.
- `ruff`/`mypy`/`pyright`/`import-linter` are still unavailable in this Python 3.14 environment; the
  test suite is the verification gate that ran here.

**Version.** `0.6.0` — M1–M3 complete enough to join Pika, read the nearby world and track entities
and inventory. Physics, commands, pathfinding and swarm remain M4–M7.

## Session 4 — 2026-11-20 — M4 physics foundation, docs naming and Read the Docs

**Prompt.** Start M4 and show an actual result or file using the module. Also update the docs for
the **mcflayer** name and a Read the Docs-style build.

**Docs/naming**

- The project and PyPI distribution are now presented consistently as **mcflayer**; the import
  package remains **pyflayer** (and `PyFlayerError` remains the exception base). README, the docs
  home, site name, module docs and architecture prose were updated.
- Stale M2 statements were corrected: the bot handler table now lists chunk/block/entity/inventory/XP
  handlers, protodef coverage is 74/74 play/toClient, `entityMetadataLoop` and the native `slot`
  codec are documented, and data docs no longer claim modern state tables exist.
- Added `.readthedocs.yaml` (Ubuntu 24.04, Python 3.12, `requirements-docs.txt`, `mkdocs.yml`) plus
  `repo_url`/`edit_uri`, edit links and the previously unlinked post-prompt page. `mkdocs build
  --strict` passes; the only output is Material's end-of-life notice (not a build warning).

**Physics (M4 foundation)**

- `physics/state.py`: `PlayerState` (feet position, velocity, yaw/pitch, ground/sprint/sneak and
  medium flags) with a `0.6 x 1.8 x 0.6` hitbox.
- `physics/controls.py`: `ControlState` with clamped forward/strafe and jump/sprint/sneak inputs.
- `physics/media.py`: water/lava/web/ladder sampling, ice/packed-ice/slime slipperiness and soul
  sand slowdown.
- `physics/collision.py`: swept AABB resolution in Y/X/Z order, whole-hitbox contact translation,
  ground detection and `0.6` step-up.
- `physics/engine.py`: 1.8 ground/air acceleration (`0.1` / `0.02`), gravity `0.08`, air drag
  `0.98`, friction `slipperiness * 0.91`, sprint/sneak multipliers, `0.42` jump, sprint jump boost,
  water/lava/ladder/web handling.
- `physics/tick.py`: `TickDriver` with absolute deadlines, bounded catch-up and an injected `Clock`.
- Top-level exports: `PhysicsEngine`, `PlayerState`, `ControlState`, `TickDriver`.

**Bug found and fixed.** The first collision pass clamped only the moving face of the AABB, which
shrunk the hitbox from `0.6` to `0.414` and let the player tunnel into a wall; the next Y clip then
pushed the player to the top of the wall. Axis clipping now computes an allowed delta and translates
the whole box, preserving its dimensions.

**Verification**

- Focused tests cover landing, reference walk velocity, sprint/sneak ordering, exact jump arc,
  wall stop, slab step-up, water and tick deadlines: `tests/test_physics.py`, 8 tests.
- `pytest -q`: **178 passed**, exit 0.
- Compared against prismarine-physics 1.8.9 on flat ground: walk terminal velocity and jump apex
  match to better than `1e-6` per tick.
- `examples/physics_demo.py` prints a 90-tick trajectory: slab step to Y=`64.5`, sprint-jump peak
  Y=`65.752203`, wall stop at Z=`13.7`, final `on_ground=True`.

**Still open for M4.** Movement packet cadence and ground flag, teleport confirmation, bot controls
and tick ownership, oracle traces for the remaining media, and the 10-minute anti-cheat run.

## Session 5 — 2026-11-21 — M4 completion and discord.py-style API docs

**Prompt.** Read the docs, complete M4, check `git diff` for work already done, track the work in a
to-do list, and write the documentation in the Read the Docs / discord.py style.

**Work already present (uncommitted).** Bot-owned physics loop, `bot/movement.py`, teleport
confirmation, oracle generator and fixtures, and the first oracle test. The audit found the driver
tests failing and exposed a few fidelity gaps.

**Fixed**

- `TickDriver` accumulated `0.05 * 3` as `0.15000000000000002`, so an exact `0.15` tick slept for an
  extra interval. Deadlines now tolerate `1e-9`.
- `measured_tps` started one interval early, reporting 15 instead of 20.
- Welford's interval count was off by one, so a perfectly regular loop reported `0.0289` jitter.
- “Late” now means a missed full deadline, not ordinary sub-millisecond scheduler lateness. Added
  `jitter_p99_ms` and an interval ring buffer.
- Ladders now climb in 1.8 style when pushing into them; jump-to-climb is 1.14+ and removed.
  Sneaking holds position on a ladder.
- `Bot` emits `entity_action` `start/stop_sprinting` and `start/stop_sneaking` before sprint/sneak
  speed changes, so servers validate movement against the correct state.

**Added tests**

- `tests/test_movement.py`: squared-delta threshold, rotation/ground/reminder packet selection,
  1.8 echo vs 1.9 `teleport_confirm`, FakeServer sprint/stop actions and one-tick jump consumption.
- `tests/test_physics.py`: stairs step-up, ladder climb and sneak hold, soul-sand slowdown, and 300
  seeded random ticks checking “never inside a solid block” and `on_ground` support.
- Oracle regeneration remains pinned to prismarine-physics 1.11.1 / minecraft-data 3.75.0.

**Verification**

- `pytest` focused M4 files: 35 passed (physics 15, movement 10, oracle 10).
- Full suite: **205 passed**.
- Idle `TickDriver` with `MonotonicClock`: **19.994 TPS**, **p99 jitter 0.83 ms**, **0 dropped**,
  **0 catch-up** ticks over 103 ticks.
- `mkdocs build --strict` after the docs rewrite (see below).

**Docs**

- `docs/modules/physics.md` rewritten as an API reference with signatures, attributes, packet and
  medium tables, oracle coverage, reference numbers, divergences and a measured jitter result.
- `docs/modules/bot.md` gained controls, packet cadence, teleport reconciliation,
  `entity_action` ordering, `PhysicsTickEvent` and limitations.
- New `docs/handoff/M4.md`; updated events, world, module index, home status, tasks and README.

**Remaining.** The roadmap's 10-minute scripted anti-cheat run on vanilla/Paper needs a live server
and was not possible in this environment.

## Session 6 — 2026-11-21 — M5 command and task layer

**Prompt.** Read the handoff, architecture, roadmap, sessions and tasks; report what is left, then
complete M5 and keep the docs updated.

**Starting point.** M1–M4 are implemented and green; `pyflayer.ext.commands` and
`pyflayer.ext.tasks` existed only as empty docstring placeholders, so M5 was entirely unimplemented.
The remaining work was therefore M5 itself (M6 pathfinder/actions and M7 swarm are still design-only,
and the M4 live anti-cheat soak is still environment-dependent).

**Implemented**

- `ext/commands/`: `errors` (the full command error tree, `CommandPrefixError(TypeError, CommandError)`),
  `view` (`StringView`, `tokenize`), `converters` (`Converter`, `Greedy`, `Range`, built-ins,
  `Literal`/`Optional`/`Union`/`Annotated`), `checks` (checks, cooldowns on the injected clock,
  `max_concurrency`, owner/dimension/proximity checks), `flags` (`FlagConverter`, `flag`,
  `parse_flags`), `context` (`Context.reply`/`send`), `core` (`Command`, `Group`, signature parsing),
  `cog` (`Cog`, `CogMeta`, `listener`), `help`, and `bot` (`commands.Bot`).
- `ext/tasks/loop.py`: `Loop` descriptor and `loop()` with wall-clock and physics-tick intervals,
  `count`, `before_loop`/`after_loop`/`error`, and cog-driven start/stop/resume.
- `commands.Bot` dispatch is address-based only (whisper, name mention, `trigger=`, or
  `dispatch_command`); `command_prefix=` raises `CommandPrefixError`.
- Extensions use a per-extension ledger; `load_extension` rolls back on failure and
  `reload_extension` restores the old module, cogs and commands atomically.
- `Bot.get_player` and `Bot.player_names` cache-style accessors.
- `examples/commands_demo.py` and `tests/test_commands.py` (23 tests).

**Verification**

```bash
source .venv/bin/activate
python -m pytest tests/test_commands.py -q   # 23 passed
python -m pytest -q                          # full suite green (228 tests)
python examples/commands_demo.py
```

Docs: new module guides (`commands`, `tasks`), API reference pages, `migrating-from-discordpy.md`,
`handoff/M5.md`; updated home, module index, reference index, tasks, README and version (`0.8.0`).

**Known limitations (M5)**

- Public-chat addressing is token-based; servers/plugins that rewrite names need `trigger=`.
- `tasks.loop(time=...)` is accepted but not scheduled; reconnect pausing is not wired.
- No slash commands, interactions, views, webhooks, permissions or feature parity (ADR-11).
- `ruff`/`mypy`/`pyright`/`import-linter` remain unavailable in this Python 3.14 environment; the test
  suite is the verification gate that ran here.
