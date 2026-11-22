# mcflayer

An asyncio Minecraft Java Edition bot library: Mineflayer's protocol, world and physics, with a
command layer shaped like discord.py. This site is the split of the original single-file blueprint
(`FirstIMp.md`) into browsable documents.

> **Name:** the project and PyPI distribution are **`mcflayer`**. The import package remains
> **`pyflayer`**, so code examples use `import pyflayer`.

> **Status:** Milestones 1–5 and 7 are implemented against **Minecraft 1.8.9 / protocol 47**: transport,
> framing/compression, AES-CFB8, the `minecraft-data` loader, protodef codecs, login and
> offline/Microsoft auth, the event bus, a bot that joins and chats on PikaNetwork, world state
> (chunks, blocks, entities, inventory, snapshots, raycast), deterministic physics with a
> drift-compensated 20 TPS loop, a discord.py-shaped command layer, and multi-bot clusters with
> shared chunk storage, staggered logins, claims, a blackboard and metrics. The bot emits
> vanilla-style movement packets, sprint/sneak `entity_action` changes and teleport confirmations.
> The roadmap's 10-minute anti-cheat soak on a live vanilla/Paper server and the 50-bot Paper soak
> remain environment-dependent gates. See the [module reference](modules/index.md),
> [session log](sessions.md) and [task board](tasks.md). Pathfinding and the action framework (M6)
> are design-only.

## Design stance

The framework is **discord.py-inspired, not a port**. It keeps what makes a bot pleasant to write and
drops everything that has no meaning in Minecraft:

- **Kept:** `Bot` + `Cog`, `@bot.event` / `@Cog.listener()`, typed command signatures with converters,
  checks, cooldowns, generated help, `tasks.loop`, `setup()`/`teardown()` extensions with atomic hot
  reload. OOP throughout — state lives on objects, not in module globals.
- **Dropped:** the discord.py spelling `command_prefix` (prefixes are opt-in via `prefix=`, and
  messages are also parsed when addressed by whisper/name mention or dispatched programmatically),
  slash commands and interactions, views and modals, webhooks, threads, permissions/roles/guilds,
  `Intents`, the `Client`/`Bot` split, and feature parity as a goal. Passing `command_prefix=` raises a
  clear `TypeError` instead of being ignored.
- **Compatibility is social, not binary:** discord.py code reads naturally, but
  `import pyflayer.ext as commands` is not a drop-in replacement. See
  [Architecture](ARCHITECTURE.md#design-stance-discordpy-inspired-not-a-port).

**Speed.** Correctness in Python first, then optional compiled fast paths. Hot spots — paletted chunk
decode, NBT, VarInt/frame scanning, the A\* inner loop and the physics tick — can be accelerated with
`numpy` first, then Rust/PyO3, Cython or C++. Native code is private, never mandatory, and must pass
the same golden tests as the pure-Python path. See
[Performance & compiled fast paths](ARCHITECTURE.md#performance-compiled-fast-paths).

## Notes and deviations

These are the opinionated choices carried over from the original brief:

- **Added modules:** `events`, `bot` (composition root), `_internal` (clock, CPU offload) and
  `testing`. They keep the dependency graph acyclic.
- **Reference version:** **1.8.9 (protocol 47)** for M1. It has the simplest complete status/login
  flow and a small vendored data subset; codec behaviour is feature-gated so newer versions are
  added with data, not rewrites. M1 was originally scoped around 1.20.4 but 1.8.9 was chosen for a
  fully working first slice. See [Sessions](sessions.md).
- **Hard dependencies:** `numpy`, `msgspec`, `cryptography`, `httpx`, `dnspython`. Everything else is
  optional.

## Documents

| Document | Contents |
|---|---|
| [Architecture](ARCHITECTURE.md) | Section 1: ADRs, layer map, package layout, module responsibilities, data flow, DX north star. Section 2: event bus, cogs/commands, world and chunk model, action scheduler, minecraft-data integration. |
| [Module reference](modules/index.md) | Per-package documentation for what is implemented, with examples and limitations. |
| [Roadmap](ROADMAP.md) | Section 3: milestones M1–M7 with scope, Definition of Done and testing, plus the risk register. |
| [Sessions](sessions.md) | Session-by-session implementation log and decisions. |
| [Tasks](tasks.md) | Living task board and known limitations. |
| [Prompts](PROMPTS.md) | Section 4: the common preamble and one mega-prompt per milestone, plus the suggested workflow. |
| [Handoff M1](handoff/M1.md) | Public symbols, invariants and deferred work after M1. |
| [Handoff M2](handoff/M2.md) | Public symbols, invariants and deferred work after M2. |
| [Handoff M3](handoff/M3.md) | World/entity/inventory symbols, invariants and deferred work after M3. |
| [Handoff M4](handoff/M4.md) | Physics/movement symbols, invariants, verification and deferred work after M4. |
| [Handoff M5](handoff/M5.md) | Command/task symbols, dispatch and extension invariants, verification after M5. |
| [Handoff M7](handoff/M7.md) | Swarm symbols, shared-world/tick invariants and deferred work after M7. |
| [Physics](modules/physics.md) | M4 player state, controls, collision, media, tick driver and fidelity. |
| [Commands](modules/commands.md) | M5 address-based dispatch, cogs, converters, checks, flags, help, extensions. |
| [Tasks](modules/tasks.md) | M5 `tasks.loop` on wall time or physics ticks. |
| [Swarm](modules/swarm.md) | M7 clusters, shared worlds, login staggering, claims, blackboard, metrics. |
| [Migrating from discord.py](migrating-from-discordpy.md) | What carries over and what is deliberately gone. |

## Building these docs with MkDocs

The docs are plain Markdown and build with [MkDocs](https://www.mkdocs.org/), which is **free and
open source** (BSD-2-Clause), written in Python, and needs no account or paid service. It reads
`mkdocs.yml` from the repository root and serves the Markdown as a static site.

```bash
python3 -m venv .venv-docs
source .venv-docs/bin/activate      # Windows: .venv-docs\Scripts\activate
pip install -r requirements-docs.txt

mkdocs serve                        # live preview at http://127.0.0.1:8000
mkdocs build                        # static site in ./site
```

Notes:

- `mkdocs serve` rebuilds on save, so editing these files updates the browser automatically.
- `mkdocs build --strict` turns broken internal links and warnings into errors; useful in CI.
- The [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) theme (MIT) is included in
  `requirements-docs.txt` for search, dark mode and better navigation. Drop it and set
  `theme.name: readthedocs` in `mkdocs.yml` to use a bundled theme with zero extra dependencies.
- **Read the Docs:** `.readthedocs.yaml` installs `requirements-docs.txt` and builds `mkdocs.yml`
  on every push. The same config works locally; `site/` is generated output and is not committed.
- **GitHub Pages:** publish `./site` with `mkdocs gh-deploy` (no extra service), or use any static host.

The single-file source (`FirstIMp.md`) is kept unchanged at the repository root for reference.
