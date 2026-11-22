# Module reference

These pages describe behavior exposed by the implementation. [Architecture](../ARCHITECTURE.md)
provides design context; package guides document APIs and limitations.

## Layer map (implemented parts in bold)

```
L8  swarm                          **BotCluster, shared chunk stores/views, login staggering,
                                      claims, blackboard, path cache, metrics**
L7  ext.commands, ext.tasks        **command bot, cogs, converters, checks, flags, help,
                                      extensions with atomic reload, tasks.loop**
L6  bot                            **Bot, chat parser, ChatQueue, world/entity/inventory handlers,
                                      physics loop and movement packets**
L5  actions, pathfinder            **ActionScheduler with leases/preemption, built-in actions,
                                      A* goals/search/planner, per-tick executor**
L4  physics                        **PhysicsEngine, controls, collision, media, TickDriver**
L3  world                          **PalettedContainer, sections, columns, entities, snapshots,
                                      raycast, ChunkStore**
L2  protocol                       **varint, buffer, types, framing, crypto, connection, status,
                                      protodef, registry, state, auth, client**
L1  data, events                   **data loader + registries; typed event bus and catalog**
L0  errors, models, _internal      **all implemented**
```

## Reference version

The documented target is **Minecraft 1.8.9 / protocol 47**. M3 adds chunk, block, entity, and
inventory state; M4 adds physics and movement; M5 adds commands and tasks; M6 adds scheduled actions
and A* pathfinding; M7 adds multi-bot clusters and shared-world components. M6 implementation does
not mean its roadmap validation gates are complete. The M7 live soak is deferred, and the live
vanilla/Paper anti-cheat soak remains environment-dependent. The vendored `minecraft-data` subset is
upstream `pc/1.8`; its `version.json` records 1.8.8, which shares protocol 47 data with the 1.8.9
reference. Vendored data alone does not establish support for other protocol versions.

Version-dependent behavior is represented through [`Features`](data.md#features) and protocol
schemas, including the pre-1.14 X/Y/Z layout of the 1.8 `position` type.

## Pages

| Page | Packages | What it covers |
|---|---|---|
| [Errors](errors.md) | `pyflayer.errors` | Exception hierarchy and structured fields |
| [Models](models.md) | `pyflayer.models` | `Vec3`, positions, `AABB`, enums, chat text, items, Protocols |
| [Internal](internal.md) | `pyflayer._internal` | `Clock`/`FakeClock`, CPU offload, logging, utilities |
| [Data](data.md) | `pyflayer.data` | `McData`, registries, shapes, features, version mapping |
| [Protocol primitives](protocol.md) | `pyflayer.protocol` | VarInts, buffers, NBT, positions, slots, UUID, BitSet |
| [Transport](transport.md) | `pyflayer.protocol.*` | Framing, compression, AES-CFB8, TCP, SRP/SRV, SLP |
| [Protodef compiler](protodef.md) | `pyflayer.protocol.protodef` | Schema compilation, packet registry, overrides |
| [Auth](auth.md) | `pyflayer.protocol.auth` | Offline UUIDs, Microsoft device flow, session join |
| [Protocol client](client.md) | `pyflayer.protocol.client` | Handshake, encryption, compression, Play stream |
| [Events](events.md) | `pyflayer.events` | Typed event bus, waiters, streams, `PhysicsTickEvent` |
| [Bot](bot.md) | `pyflayer.bot` | Join, chat, health, world, inventory, physics, movement, reconnect |
| [World](world.md) | `pyflayer.world` | Chunks, blocks, entities, inventory windows, snapshots, raycast |
| [Physics](physics.md) | `pyflayer.physics` | Player state, controls, swept collision, media, `TickDriver` |
| [Pathfinding](pathfinding.md) | `pyflayer.pathfinder` | Goals, A* search, snapshot planner, per-tick executor |
| [Actions](actions.md) | `pyflayer.actions` | Resource scheduler, leases, preemption, built-in actions, survival monitor |
| [Commands](commands.md) | `pyflayer.ext.commands` | Address-based dispatch, cogs, converters, checks, cooldowns, flags, help, extensions |
| [Tasks](tasks.md) | `pyflayer.ext.tasks` | `tasks.loop` on wall time or physics ticks |
| [Swarm](swarm.md) | `pyflayer.swarm` | Clusters, shared worlds, login staggering, claims, blackboard, path cache, metrics |

## Public import surface

```python
import pyflayer

pyflayer.McData.load("1.8.9")
pyflayer.PacketReader, pyflayer.PacketWriter
pyflayer.FrameCodec
pyflayer.Connection
pyflayer.PacketRegistry
pyflayer.ServerStatus, pyflayer.ping
pyflayer.ProtocolClient, pyflayer.StateMachine, pyflayer.ConnectionState
pyflayer.Bot, pyflayer.ChatEvent, pyflayer.EventBus
pyflayer.events.PhysicsTickEvent
pyflayer.World, pyflayer.ChunkColumn, pyflayer.EntityTracker, pyflayer.PalettedContainer
pyflayer.PhysicsEngine, pyflayer.PlayerState, pyflayer.ControlState, pyflayer.TickDriver
pyflayer.physics.move_box, pyflayer.physics.MoveResult, pyflayer.physics.Medium
pyflayer.actions.ActionScheduler, pyflayer.actions.GoTo, pyflayer.actions.Dig
pyflayer.pathfinder.PathPlanner, pyflayer.pathfinder.GoalBlock, pyflayer.pathfinder.PathExecutor
pyflayer.ext.commands.Bot, pyflayer.ext.commands.Cog, pyflayer.ext.commands.command
pyflayer.ext.tasks.loop
pyflayer.swarm.BotCluster, pyflayer.swarm.SharedWorldRegistry, pyflayer.swarm.LoginStaggerPolicy
pyflayer.swarm.ClaimRegistry, pyflayer.swarm.Blackboard, pyflayer.swarm.PathCache
pyflayer.Vec3, pyflayer.BlockPos, pyflayer.ChatComponent, pyflayer.ChatMessage
pyflayer.errors
```

The snippet shows selected exports. Package `__all__` declarations identify exported names; this
overview does not guarantee exhaustive symbol coverage.
