# API reference

This reference uses [mkdocstrings](https://mkdocstrings.github.io/) to render documented Python
objects from the source. Pages follow the package layout and expose signatures and annotations
where available; docstring detail varies by object.

The [guide](../modules/index.md) describes module behavior and limitations. The generated reference
documents the Python API; it does not claim protocol-version or feature completeness.

!!! note "Reference version"
    The documented reference target is **Minecraft 1.8.9 / protocol 47**. Data files are vendored
    for `1.8`, `1.20.4` and `26.1`; availability of a snapshot does not imply protocol or gameplay
    support for that version.

## How these pages are generated

The directives below are rendered at build time from the configured Python source path:

```markdown
::: pyflayer.bot.bot.Bot
    options:
      members: [connect, run, chat]
```

`mkdocstrings` imports the package from `src/` and renders Google-style docstrings and type
annotations according to the options in `mkdocs.yml`. With `show_if_no_docstring` enabled, selected
objects without docstrings may still appear; the generated pages do not guarantee that every public
symbol is documented.

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
| [Pathfinding](pathfinding.md) | `pyflayer.pathfinder` | Goals, A* search, `PathPlanner`, `PathExecutor` |
| [Actions](actions.md) | `pyflayer.actions` | Scheduler, leases, preemption, built-in actions |
| [Testing](testing.md) | `pyflayer.testing` | `FakeServer` for offline integration tests |
| [CLI](cli.md) | `pyflayer.cli` | `pyflayer-connect` and `pyflayer-status` entry points |
| [Commands](commands.md) | `pyflayer.ext.commands` | Address-based dispatch, cogs, converters, checks, flags, help, extensions |
| [Tasks](tasks.md) | `pyflayer.ext.tasks` | `tasks.loop` aligned to wall time or physics ticks |
| [Swarm](swarm.md) | `pyflayer.swarm` | Clusters, shared worlds, login staggering, claims, blackboard, path cache, metrics |

## Public API policy

- Package `__all__` declarations identify exported names. This reference documents selected API
  surfaces and does not guarantee exhaustive symbol coverage or compatibility stability.
- API changes and known limitations are tracked in [Sessions](../sessions.md) and the
  [task board](../tasks.md).
- `PROTOCOL_VERSION` (`47`) and `REFERENCE_VERSION` (`"1.8.9"`) identify the documented reference
  target. Other loadable data snapshots do not establish protocol support.
- APIs use the [`pyflayer.errors`](errors.md) hierarchy where specified; callers should also account
  for built-in exceptions documented by individual functions and dependencies.
