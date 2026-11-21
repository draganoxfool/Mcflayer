# PyFlayer Hardening Pass: correctness, speed, and latest-version scaling

You are working on PyFlayer, a discord.py-inspired Minecraft bot framework in Python.
The source of truth is docs/ARCHITECTURE.md — its ADRs override everything else, including this prompt where they conflict.

## Context: known gaps and external failures you must not repeat

Mineflayer (the JS leader) got hard-kicked by vanilla 1.26.3 servers for months because it never sent the
`client_tick_end` packet (added 1.21.2) and sent 2 movement packets per tick. Native clients send exactly
one movement + one tick_end per server tick. pyCraft/spockbot/Lodestone all died of version rot.
Lessons baked into the requirements below.

## 1. Tick-boundary packet ownership (NEW ADR)

- Add ADR-13: The TickDriver owns ALL tick-boundary outbound packets. Per server tick it emits exactly
  one move/look packet AND the tick-end packet required by 1.21.2+ (version-gated via Features).
- Actions and handlers must NEVER send movement/tick packets (ADR-5 already covers movement — extend
  its docstring and enforce with a lint/CI check: grep tests assert no `send()` of movement-class packets
  outside handlers/movement.py).
- Golden test: record a real 1.21.2+ client's packet stream; assert PyFlayer's tick stream is
  packet-for-packet identical (one move, one tick_end, correct order, no extras).

## 2. Anti-cheat conformance testing (upgrade the oracle policy)

- The Mineflayer oracle is NOT sufficient ground truth — Mineflayer itself failed on 1.26.3. Add a second
  tier: behavioral conformance fixtures recorded against real server software (Vanilla, Paper, Spigot)
  per supported version. docs/version-support-matrix.md gains a column "conformance: pass/fail" that must
  be green before a version ships as "supported".
- Add tools/conformance/ harness: spin up a real server in CI (docker), connect PyFlayer, run a scripted
  session (join, walk, jump, place, break, chat), capture server-side observations (no kicks, correct
  block state, accepted transactions).

## 3. Humanization / detection-resistance layer (new, optional)

- New package `pyflayer/stealth/`: TimingJitter (bounded ±2-4ms on action scheduling, seeded, injectable
  Clock-aware so tests stay deterministic), LookNoise (small per-tick look variance when idle, disabled
  during precision tasks like placing), ChatHumanizer (optional typing cadence in ChatQueue).
- All stealth is OFF by default and toggled per-bot: `Bot(stealth=True)`. Never make it mandatory —
  speedrun/farm users want determinism.
- ADR-14: stealth affects scheduling only, never physics correctness; golden tests run with stealth off.

## 4. Chat signing surface (1.19+)

- Inventory the signed-chat / player-chat-report requirements per version in protocol/native/.
- ChatQueue must handle unsigned-&gt;signed transition correctly per version (system_chat vs player_chat,
  last-seen update packets). Golden tests from recorded streams for 1.19, 1.20.2, 1.21.x.
- Document in migrating-from-discordpy.md and in docs/ that signed chat affects what bots can say.

## 5. Performance: make the hot paths fast, keep pure-Python fallback

Priority order (already in the doc's perf section — execute it now):
a) Paletted chunk decode → numpy vectorized decode in world/palette.py; measure against fixture corpus.
b) NBT parse → numpy/struct fast path for the hot tag types (compound/list/int arrays).
c) VarInt/frame scanning → memoryview-based loop first; only consider native (PyO3/maturin abi3 wheel)
   if the pure path misses the 50ms tick budget on the benchmark corpus.
d) A* inner loop + physics tick → keep pure Python but profile; only compile if benchmarks demand it.
Rules: native code lives in pyflayer._native.*, imported via the guarded __init__, never required at
runtime, same golden tests run against both paths. CI benchmark gate: native path that isn't measurably
faster gets removed. Run CI benchmarks on decode, A*, and tick; post results as a PR comment artifact.

## 6. Swarm scaling

- Validate the ChunkStore refcount/dedup rules with a stress test: 32 bots in one area must hold ~1x
  chunk memory; assert via tracemalloc in tests.
- One TickDriver per cluster is load-bearing — add a soak test: 64 bots, 10k ticks, assert no tick
  overrun beyond budget, no lease deadlock (arbitration is under one asyncio.Lock; add a fuzz test
  with randomized action submissions and a watchdog).

## 7. Latest-version scaling process (make version-adding boring)

- Automate the version-bump pipeline: script that takes a new minecraft-data pin, regenerates registries,
  runs golden + conformance + fake-server login flow, and emits the support-matrix row (pass/fail per
  layer). A version is "supported" only when all rows pass.
- Delete any scattered `if version &gt;= (1, x, y)` outside data/ and protocol/native/; route everything
  through Features checks. Add a CI lint for this.
- Target: adding support for a new Minecraft minor version is a PR that changes the data pin, the
  features table, and the matrix row — nothing else.

## Definition of done

- [ ] ADR-13 and ADR-14 written; ADR-5 extended and CI-enforced
- [ ] Tick stream golden test green on 1.21.2+ and on the latest protocol in minecraft-data
- [ ] Conformance harness runs Vanilla + Paper in CI for the two latest supported versions
- [ ] Stealth package exists, deterministic, off by default, golden-tested off
- [ ] Signed-chat golden tests green for 1.19 / 1.20.2 / latest
- [ ] Benchmark CI gate live with posted results; pure-Python path still passes all tests
- [ ] 32-bot memory test + 64-bot soak test in CI
- [ ] Version-bump pipeline script works end-to-end on the newest minecraft-data commit