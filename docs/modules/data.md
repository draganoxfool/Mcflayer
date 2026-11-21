# Data (`pyflayer.data`)

`McData.load(version)` turns a `minecraft-data` checkout into one immutable snapshot. It is cached
per `(version key, data directory)`.

```python
from pyflayer.data import McData

mc = McData.load("1.8.9")
mc.version.protocol  # 47
mc.blocks["stone"].id  # 1
mc.blocks.state_id("stone")  # 16  (legacy (id << 4) | meta)
mc.shapes.boxes_for("stone")  # (AABB(0,0,0,1,1,1),)
```

## Data directory resolution

1. `PYFLAYER_DATA_DIR` — a full `minecraft-data/data` checkout.
2. `<repo>/data` — the vendored 1.8 subset in this repository.
3. `./data`.

`dataPaths.json` is honoured, including the upstream nested-edition layout. Missing files raise
`DataError`; an unknown version raises `UnsupportedVersion` with a short list of available versions.

## Registries

| Registry | Entry fields |
|---|---|
| `BlockRegistry` | `id, name, display_name, hardness, resistance, stack_size, diggable, transparent, emit_light, filter_light, bounding_box` |
| `ItemRegistry` | `id, name, display_name, stack_size, max_durability` |
| `EntityRegistry` | `id, name, display_name, kind, category, width, height` |
| `BiomeRegistry` | `id, name, display_name, category, dimension, temperature, rainfall, depth, color` |
| `EffectRegistry` | `id, name, display_name, kind` |
| `FoodRegistry` | `id, name, display_name, stack_size, food_points, saturation, …` |

All registries support `name`, `id`, `"minecraft:"` prefix stripping, `get(default)`, `in`,
`names()`, `by_name()`, `by_id()`. Unknown lookups raise `MissingRegistryEntry`.

### Legacy block states (1.8)

1.8 has no global block-state ids. mcflayer exposes:

```python
state_id = mc.blocks.legacy_state_id(block.id, metadata)  # (block_id << 4) | meta
block, meta = mc.blocks.from_legacy_state_id(state_id)
```

`Features.block_state_ids` is `False` for 1.8 and `True` for 1.13+. Modern global state tables
(`minStateId`/`maxStateId`) are **not vendored yet**: only the 1.8 data set ships, so lookups use the
legacy path above. `PalettedContainer` can decode modern chunk layouts, but the corresponding block
registry data is still deferred.

## Shapes

`ShapeTable` precomputes `AABB` tuples:

```python
mc.shapes.boxes_for("stone")  # full cube
mc.shapes.boxes_for("air")  # ()
mc.collision_boxes(mc.blocks.state_id("stone"))
```

`blocks` values in `blockCollisionShapes.json` may be a single shape id or a metadata-indexed list;
both are supported. Modern state-id collision lookup needs `minStateId`/`maxStateId` ranges plus
modern data and remains deferred.

## Features

`Features.for_version("1.8.9")` returns frozen booleans such as:

| Flag | 1.8.9 | 1.20.4 |
|---|---|---|
| `position_packed_xzy` | ❌ | ✅ |
| `network_nbt_nameless` | ❌ | ✅ |
| `slot_item_id_varint` | ❌ | ✅ |
| `block_state_ids` | ❌ | ✅ |
| `configuration_state` | ❌ | ✅ |
| `compression_supported` | ✅ | ✅ |

Protocol code must ask flags (or read the version's schema) instead of comparing versions directly.

## Versions

`version_key("1.8.9") == "1.8"`, `protocol_for("1.8.9") == 47`,
`version_for_protocol(47) == "1.8"`. Aliases map 1.8.x to the data key `1.8`.
