# mcflayer

mcflayer is an asyncio library for Minecraft Java Edition bots. It provides protocol, world,
physics, pathfinding, action, command, and multi-bot components. The documented reference target is
Minecraft 1.8.9 (protocol 47); vendored data for other versions does not establish support for
those protocols.

> **Name:** the project and PyPI distribution are **`mcflayer`**. The import package remains
> **`pyflayer`**, so code examples use `import pyflayer`.

> **Status:** M1–M7 components are implemented for the documented reference target. M6 includes
> pathfinding and scheduled actions; its roadmap validation gates remain outstanding. M7 includes
> multi-bot clusters and shared-world components; its live soak is deferred. The live vanilla/Paper
> anti-cheat soak also remains an environment-dependent gate. See the
> [module reference](modules/index.md), [session log](sessions.md), and [task board](tasks.md).

## Design stance

The command framework is **discord.py-inspired, not a port**. It provides cogs, listeners, typed
commands, converters, checks, cooldowns, help, extensions, and scheduled tasks. Discord-specific
surfaces such as interactions, views, webhooks, and guild permissions are not part of the API.

- Prefixes are configured with `prefix=`. Dispatch also supports addressed messages and
  programmatic invocation; `command_prefix=` is not supported.
- The package is not a drop-in replacement for discord.py. See
  [Architecture](ARCHITECTURE.md#design-stance-discordpy-inspired-not-a-port).

## Notes and deviations

The implementation uses the following project-specific choices:

- **Added modules:** `events`, `bot` (composition root), `_internal` (clock, CPU offload) and
  `testing`. They keep the dependency graph acyclic.
- **Reference version:** **1.8.9 (protocol 47)**. The vendored `pc/1.8` data is a subset; its
  presence does not imply support for all protocols or features in that data. See
  [Sessions](sessions.md).
- **Hard dependencies:** `numpy`, `msgspec`, `cryptography`, `httpx`, `dnspython`. Everything else is
  optional.

## Documents

| Document | Contents |
|---|---|
| [Architecture](ARCHITECTURE.md) | Architecture decisions, package layers, data flow, and component responsibilities. |
| [Module reference](modules/index.md) | Implemented package guides, examples, and limitations. |
| [Roadmap](ROADMAP.md) | Milestone scope, completion criteria, tests, and risks. |
| [Sessions](sessions.md) | Implementation history and decisions. |
| [Tasks](tasks.md) | Open tasks and known limitations. |
| [Prompts](PROMPTS.md) | Milestone prompts and workflow notes. |
| [Handoff M1](handoff/M1.md) | M1 public symbols, invariants, and deferred work. |
| [Handoff M2](handoff/M2.md) | M2 public symbols, invariants, and deferred work. |
| [Handoff M3](handoff/M3.md) | M3 world, entity, and inventory details. |
| [Handoff M4](handoff/M4.md) | M4 physics and movement details. |
| [Handoff M5](handoff/M5.md) | M5 command, task, and extension details. |
| [Handoff M7](handoff/M7.md) | M7 swarm and shared-world details. |
| [Physics](modules/physics.md) | Player state, controls, collision, media, and tick driver. |
| [Commands](modules/commands.md) | Dispatch, cogs, converters, checks, flags, help, and extensions. |
| [Tasks](modules/tasks.md) | `tasks.loop` on wall time or physics ticks. |
| [Swarm](modules/swarm.md) | Clusters, shared worlds, login staggering, coordination, and metrics. |
| [Migrating from discord.py](migrating-from-discordpy.md) | API similarities and differences. |

## Building these docs with MkDocs

The documentation uses [MkDocs](https://www.mkdocs.org/) with configuration in `mkdocs.yml`.

```bash
python3 -m venv .venv-docs
source .venv-docs/bin/activate      # Windows: .venv-docs\Scripts\activate
pip install -r requirements-docs.txt

mkdocs serve                        # live preview at http://127.0.0.1:8000
mkdocs build                        # static site in ./site
```

Notes:

- `mkdocs serve` starts a local preview; `mkdocs build --strict` treats warnings as errors.
- The Material theme and documentation dependencies are listed in `requirements-docs.txt`.
- Read the Docs uses `.readthedocs.yaml` to build the configured site.

`FirstIMp.md` remains at the repository root as the original blueprint.
