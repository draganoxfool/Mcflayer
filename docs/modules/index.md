# Module reference

This section documents every package that exists after Milestone 7. It is the practical companion to
[Architecture](../ARCHITECTURE.md): the architecture describes the full target, these pages describe
what is **actually implemented today** and how to use it.

## Layer map (implemented parts in bold)

```
L8  swarm                          **BotCluster, shared chunk stores/views, login staggering,
                                      claims, blackboard, path cache, metrics**
L7  ext.commands, ext.tasks        **command bot, cogs, converters, checks, flags, help,
                                      extensions with atomic reload, tasks.loop**
L6  bot                            **Bot, chat parser, ChatQueue, world/entity/inventory handlers,
                                      physics loop and movement packets**
L5  actions, pathfinder            (empty)
L4  physics                        **PhysicsEngine, controls, collision, media, TickDriver**
L3  world                          **PalettedContainer, sections, columns, entities, snapshots,
                                      raycast, ChunkStore**
L2  protocol                       **varint, buffer, types, framing, crypto, connection, status,
                                      protodef, registry, state, auth, client**
L1  data, events                   **data loader + registries; typed event bus and catalog**
L0  errors, models, _internal      **all implemented**
```

## Reference version

The reference target is **Minecraft 1.8.9 / protocol 47**. M3 adds chunk/block/entity/inventory state
on top of the M2 bot; M4 adds deterministic physics, a drift-compensated 20 TPS loop, movement
packet cadence, sprint/sneak `entity_action` changes and teleport reconciliation; M5 adds the
discord.py-inspired command and task layer; M7 adds multi-bot clusters with shared chunk storage,
staggered logins, coordination primitives and metrics. Pathfinding and the action framework (M6)
remain design-only. The vendored `minecraft-data` subset is
upstream `pc/1.8`; its `version.json` records 1.8.8, which shares protocol 47 and data with 1.8.9.

Version differences are expressed through [`Features`](data.md#features) and the schema itself (for
example, 1.8's `position` type is a protodef bitfield with the pre-1.14 X/Y/Z layout). There are no
scattered version comparisons in protocol code.

## Pages

| Page | Packages | What it covers |
|---|---|---|
| [Errors](errors.md) | `pyflayer.errors` | The single exception tree, structured fields |
| [Models](models.md) | `pyflayer.models` | `Vec3`, positions, `AABB`, enums, chat text, items, Protocols |
| [Internal](internal.md) | `pyflayer._internal` | `Clock`/`FakeClock`, CPU offload, logging, utilities |
| [Data](data.md) | `pyflayer.data` | `McData`, registries, shapes, features, version mapping |
| [Protocol primitives](protocol.md) | `pyflayer.protocol` | VarInts, buffers, NBT, positions, slots, UUID, BitSet |
| [Transport](transport.md) | `pyflayer.protocol.*` | Framing, compression, AES-CFB8, TCP, SRP/SRV, SLP |
| [Protodef compiler](protodef.md) | `pyflayer.protocol.protodef` | Schema compilation, packet registry, overrides |
| [Auth](auth.md) | `pyflayer.protocol.auth` | Offline UUIDs, Microsoft device flow, session join |
| [Protocol client](client.md) | `pyflayer.protocol.client` | Handshake, encryption, compression, Play stream |
| [Events](events.md) | `pyflayer.events` | Typed event bus, waiters, streams, `PhysicsTickEvent` |
| [Bot](bot.md) | `pyflayer.bot` | Join, keep-alive, chat, health/respawn, world/entity/inventory handlers, physics controls, movement packets, reconnect |
| [World](world.md) | `pyflayer.world` | Chunks, blocks, entities, inventory windows, snapshots, raycast |
| [Physics](physics.md) | `pyflayer.physics` | Player state, controls, swept collision, media, `TickDriver`, movement fidelity |
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
pyflayer.ext.commands.Bot, pyflayer.ext.commands.Cog, pyflayer.ext.commands.command
pyflayer.ext.tasks.loop
pyflayer.swarm.BotCluster, pyflayer.swarm.SharedWorldRegistry, pyflayer.swarm.LoginStaggerPolicy
pyflayer.swarm.ClaimRegistry, pyflayer.swarm.Blackboard, pyflayer.swarm.PathCache
pyflayer.Vec3, pyflayer.BlockPos, pyflayer.ChatComponent, pyflayer.ChatMessage
pyflayer.errors
```

Everything exported is listed in the package `__all__`; the modules above are considered private
implementation detail unless documented here.
