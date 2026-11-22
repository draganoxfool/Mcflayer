# World (`pyflayer.world`)

World state is **immutable per section** and mutable per world. Servers send whole chunk columns and
small block updates; the bot keeps the current dimension in `Bot.world`, entities in `Bot.entities`
and inventory windows in `Bot.inventory`.

## Data model

```
WorldSnapshot ──copy──> World ──{ChunkPos: ChunkColumn}──> ChunkSection (immutable)
                                                              └── PalettedContainer
```

| Type | Role |
|---|---|
| `PalettedContainer` | Sparse or direct block-state storage. Kinds: `SINGLE`, `INDIRECT`, `DIRECT`. Copy-on-write and numpy-backed. |
| `ChunkSection` | 16×16×16 immutable section, YZX index order `(y << 8) \| (z << 4) \| x`, plus block/sky light. |
| `ChunkColumn` | 16×256×16 column: sections, biomes, block entities, `version`. Writes replace a section. |
| `World` | `{ChunkPos: ChunkColumn}` for one dimension, block reads/writes, `find_blocks`, `raycast`. |
| `WorldSnapshot` | Cheap read-only copy; safe to hand to a worker thread while the bot keeps updating. |
| `ChunkStore` | Refcounted columns for M7 bot clusters. Not used by a single `Bot`. |
| `EntityTracker` / `Entity` | Spawn/move/teleport/metadata/equipment/attach state for entities and players. |
| `BlockState` | Resolved name, properties and collision boxes for a state id. |

Block state ids follow the reference version: 1.8 uses `(block_id << 4) | metadata`.
`PalettedContainer.decode()` also implements the modern single/indirect/direct wire format for future
versions, but 1.8 is the only vendored data set.

## Bot usage

```python
from pyflayer import BlockPos, Vec3

bot = Bot("Steve", host="play.example.org")
await bot.connect()

stone = bot.find_blocks("stone", within=16, count=5)
state = bot.world.block_at(BlockPos(0, 64, 0))
hit = bot.world.raycast(Vec3(0, 70, 0), Vec3(0, -1, 0), max_dist=8)

for entity in bot.entities.all():
    if entity.is_player:
        print(entity.name, entity.position)
```

`World.block_state_id()` raises `ChunkNotLoaded` or `OutOfWorldBounds`; use `block_state_id_or(pos,
default)` when probing. `World.set_block_state()` returns `False` for an unloaded chunk or a no-op.
`World.snapshot(Bounds(...))` copies only columns overlapping optional bounds.

Inventory (window 0) uses the 1.8 slot layout: 0 crafting output, 1–4 crafting grid, 5–8 armour,
9–35 main inventory, 36–44 hotbar. `Bot.inventory.held_item` follows the selected hotbar slot.

```python
item = bot.inventory.held_item
if item is not None:
    print(item.item_id, item.count)
```

## Events

Handlers update world/entity/inventory state **before** dispatching, so listeners see the new state.

| Event | Handler | Payload |
|---|---|---|
| `ChunkLoadEvent` | `on_chunk_load` | position, section count, non-air count |
| `ChunkUnloadEvent` | `on_chunk_unload` | chunk position (reserved: 1.8 has no unload packet) |
| `BlockUpdateEvent` | `on_block_update` | position, new/old state id |
| `EntitySpawnEvent` | `on_entity_spawn` | `Entity` |
| `EntityMoveEvent` | `on_entity_move` | `Entity`, previous position |
| `EntityGoneEvent` | `on_entity_gone` | removed `Entity` |
| `EntityMetadataEvent` | `on_entity_metadata` | entity id, metadata |
| `InventoryChangedEvent` | `on_inventory_changed` | window id, slot (`-1` = whole window), item |
| `DimensionChangeEvent` | `on_dimension_change` | dimension, previous |
| `ExperienceEvent` | `on_experience` | bar, level, total |

Respawn and dimension change clear the world and entity tracker (inventory persists, as in vanilla).
A `map_chunk` with `groundUp=False` is merged into the existing column instead of replacing it.

## Protocol coverage

`protocol/native/chunk_data.py` decodes 1.8 chunk payloads: block states, block light, optional sky
light, and biomes. In 1.8, block entities arrive separately in `tile_entity_data` packets; the bot
stores their NBT only when the corresponding column is loaded. `protocol/native/entity_metadata.py`
implements the 1.8 `entityMetadataLoop` codec. Codec or data presence alone does not establish
support for a different protocol version.

## Limitations

- The repository vendors data for multiple versions, but that does not make every version's
  connection, packet, world, or bot behavior supported. Modern paletted decode is exercised by
  tests; live modern-server compatibility is not established here.
- Chunk batch (`chunk_batch_start/finished`) is a 1.20.2+ flow and is not implemented.
- `raycast`/`find_blocks` are queries only; M4 physics reads `collision_boxes`, and pathfinding is
  M6+.
- Light arrays are stored but lighting is not recomputed client-side.
- Block entities are exposed as raw NBT mappings, not typed objects.
