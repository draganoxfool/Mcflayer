# `pyflayer.world`

World state is **immutable per section** and mutable per world. Servers send whole chunk columns and
small block updates; the bot keeps the current dimension in `Bot.world`, entities in `Bot.entities`
and inventory windows in `Bot.inventory`.

```python
from pyflayer.world import World, WorldSnapshot, ChunkColumn, ChunkSection, BlockState, EntityTracker, Entity
```


### New API modules

The action primitives were split into focused modules since M5:

| Module | Key functions |
|---|---|
| `pyflayer.bot.windows` | Window packet operations: `select_hotbar()`, `click_slot()`, `shift_click_slot()`, `drop_slot()`, `close_window()` |
| `pyflayer.bot.interactions` | Block/item packet primitives: `swing_arm()`, `use_item()`, `place_block()`, `start_digging()`, `finish_digging()`, `cancel_digging()`, `break_block()` |

Both modules are thin delegates off `Bot`; the `Bot` methods themselves have been refactored to delegate to them.

- `bot.select_hotbar(slot)` selects a hotbar slot
- `bot.click_slot(window, slot, mode=ClickMode.LEFT, action=...)` sends a window click
- `bot.use_item()` uses the block_place sentinel (cursor at -1,-1,-1, dir -1)
- `bot.place_block(pos, face)` places a block at the given position and direction
- `bot.start_digging(pos, face)` starts digging a block
- `bot.break_block(pos, face, delay=...)` breaks a block with optional delay

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Data model

```text
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
| `EntityTracker` / `Entity` | Spawn/move/teleport/metadata/equipment/attach state for entities and players. |
| `BlockState` | Resolved name, properties and collision boxes for a state id. |

Block state ids follow the reference version: 1.8 uses `(block_id << 4) | metadata`. `PalettedContainer.decode()` also implements the modern single/indirect/direct wire format for future versions, but 1.8 is the only vendored data set.

## Bot usage

```python
from pyflayer import BlockPos, Bot, Vec3

bot = Bot("Steve", host="play.example.org")
await bot.connect()

stone = bot.find_blocks("stone", within=16, count=5)
state = bot.world.block_at(BlockPos(0, 64, 0))
hit = bot.world.raycast(Vec3(0, 70, 0), Vec3(0, -1, 0), max_dist=8)

for entity in bot.entities.all():
    if entity.is_player:
        print(entity.name, entity.position)
```

**Key methods**

| Method | Meaning |
|---|---|
| `find_blocks(matching, within, around, count)` | Find nearby blocks matching a name/criteria |
| `block_at(pos)` | Get block state at a position |
| `block_state_id_or(pos, default)` | Get block state ID, returns default if chunk not loaded |
| `set_block_state(pos, state_id)` | Set block state, returns False for unloaded chunk |
| `raycast(origin, direction, max_dist)` | Raycast through the world |
| `snapshot(bounds)` | Copy a read-only view of selected columns |
| `is_loaded(chunk_pos)` | Check if a chunk is loaded |

## Inventory

Inventory (window 0) uses the 1.8 slot layout: 0 crafting output, 1–4 crafting grid, 5–8 armour,
9–35 main inventory, 36–44 hotbar. `Bot.inventory.held_item` follows the selected hotbar slot.

```python
from pyflayer import ItemStack

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

`protocol/native/chunk_data.py` decodes the 1.8 chunk payload (block states, block light, sky light,
biomes, block entities). `protocol/native/entity_metadata.py` implements `entityMetadataLoop` as a
native protodef codec, which completes the play state: every play/toClient and play/toServer packet
compiles for 1.8.9. The registry maps the `slot` type to the native `ItemStack` codec for 1.8–1.20.4
instead of exposing the JSON container's raw `blockId`/`itemCount` dict.

## Limitations

- Only 1.8.9 data is vendored; modern paletted decode is tested synthetically, not against a live
  modern server.
- Chunk batch (`chunk_batch_start/finished`) is a 1.20.2+ flow and is not implemented.
- `raycast`/`find_blocks` are queries only; M4 physics reads `collision_boxes`, and pathfinding is
  M6+.
- Light arrays are stored but lighting is not recomputed client-side.
- No Mineflayer oracle fixtures for chunk decode or the 441-column memory benchmark yet (M3
  hardening).
- Block entities are decoded from chunk data and exposed as raw NBT, not typed objects.

## Quick example

```python
from pyflayer import Bot, BlockPos, Vec3
import asyncio

bot = Bot("Steve", host="play.pika-network.net")
await bot.connect()

# Find nearby blocks
stones = bot.find_blocks("stone", within=32, count=10)
print(f"Found {len(stones)} stone blocks")

# Raycast from above
origin = Vec3(0, 70, 0)
direction = Vec3(0, -1, 0)
hit = bot.world.raycast(origin, direction, max_dist=64)
if hit:
    print(f"Hit block at {hit.pos}, face {hit.face}, distance {hit.distance}")

# Snapshot a region
snapshot = bot.world.snapshot()
print(f"World snapshot covers {len(snapshot.chunks)} chunks")

await bot.close()
```