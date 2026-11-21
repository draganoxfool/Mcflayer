# API reference

This is the generated reference for every public module in **mcflayer 0.8.0**, built with
[mkdocstrings](https://mkdocstrings.github.io/) directly from the source. It follows the layout of
the discord.py Read the Docs site: one page per module, every public class and function with its
signature, parameters, attributes, return values and raised exceptions.

The guide pages ([Guide](../modules/index.md)) explain *why* things work the way they do; these
pages are the exact contract you code against.

!!! note "Reference version"
    Everything here targets **Minecraft 1.8.9 / protocol 47** unless a symbol is marked otherwise.
    Version-dependent behaviour is feature-gated through [`Features`](data.md#features),
    not through scattered version checks.

## How these pages are generated

The directives below are rendered at build time, so the reference can never drift from the code:

```markdown
::: pyflayer.bot.bot.Bot
    options:
      members: [connect, run, chat]
```

`mkdocstrings` imports the package from `src/`, reads the Google-style docstrings and type
annotations, and links every type to its defining page. If a symbol is missing a docstring it still
appears, with its signature, so the public surface is always complete.

## Module map

| Page | Import | What it documents |
|---|---|---|
| [`pyflayer`](pyflayer.md) | `import pyflayer` | Convenience re-exports and version constants |
| [Errors](errors.md) | `pyflayer.errors` | The exception tree and structured fields |
| [Models](models.md) | `pyflayer.models` | `Vec3`, positions, `AABB`, enums, chat components, items |
| [Internal](internal.md) | `pyflayer._internal` | `Clock`, `MonotonicClock`, `FakeClock`, `run_cpu`, logging |
| [Data](data.md) | `pyflayer.data` | `McData`, registries, shapes, `Features`, version mapping |
| [Protocol](protocol.md) | `pyflayer.protocol` | VarInts, readers/writers, NBT, framing, crypto, connection, status, client |
| [Protodef compiler](protodef.md) | `pyflayer.protocol.protodef` | Schema compilation, packet registry |
| [Auth](auth.md) | `pyflayer.protocol.auth` | Offline UUIDs, Microsoft device flow, session join |
| [Events](events.md) | `pyflayer.events` | `EventBus`, waiters, and every catalog event |
| [Bot](bot.md) | `pyflayer.bot` | `Bot`, `BotState`, chat, movement tracker, inventory |
| [World](world.md) | `pyflayer.world` | Chunks, paletted storage, entities, snapshots, raycast |
| [Physics](physics.md) | `pyflayer.physics` | `PlayerState`, `PhysicsEngine`, `TickDriver`, collision |
| [Testing](testing.md) | `pyflayer.testing` | `FakeServer` for offline integration tests |
| [CLI](cli.md) | `pyflayer.cli` | `pyflayer-connect` and `pyflayer-status` entry points |
| [Commands](commands.md) | `pyflayer.ext.commands` | Address-based dispatch, cogs, converters, checks, flags, help, extensions |
| [Tasks](tasks.md) | `pyflayer.ext.tasks` | `tasks.loop` aligned to wall time or physics ticks |

## Public API policy

- A symbol is public when it is listed in its package's `__all__` **and** documented here. Anything
  else is implementation detail and may change in a minor release.
- Public names are stable within a milestone; breaking changes are recorded in
  [Sessions](../sessions.md) and the [task board](../tasks.md).
- `PROTOCOL_VERSION` (`47`) and `REFERENCE_VERSION` (`"1.8.9"`) describe the reference target, not
  the only data snapshot the code knows how to load.
- Everything raises from the [`pyflayer.errors`](errors.md) tree; no library path raises a bare
  built-in exception.
