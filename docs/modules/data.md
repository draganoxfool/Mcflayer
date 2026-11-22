# Data (`pyflayer.data`)

`McData.load(version, *, edition="pc")` loads a versioned snapshot from Minecraft data files. Loaded
snapshots are cached by data key and data-directory path.

```python
from pyflayer.data import McData

mc = McData.load("1.8.9")
mc.version.protocol  # 47
mc.blocks["stone"].id  # 1
mc.blocks.state_id("stone")  # 16  (legacy (id << 4) | meta)
mc.shapes.boxes_for("stone")  # (AABB(0,0,0,1,1,1),)
```

## Data directory resolution

1. `PYFLAYER_DATA_DIR` — a data directory containing `dataPaths.json`.
2. The package's `_data` directory, when present.
3. `<repo>/data`.
4. `./data`.

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

Registries support `registry[name_or_id]`, `get(key, default=None)`, membership checks, `names()`,
`by_name()`, and `by_id()`. String lookups are lower-cased and strip a leading `minecraft:`.
Unknown indexed lookups raise `MissingRegistryEntry`; `get()` returns its default.

### Legacy block states (1.8)

1.8 has no global block-state ids. mcflayer exposes:

```python
state_id = mc.blocks.legacy_state_id(block.id, metadata)  # (block_id << 4) | meta
block, meta = mc.blocks.from_legacy_state_id(state_id)
```

`Features.block_state_ids` is `False` for 1.8 and `True` for 1.13+. The repository includes data
directories for 1.8, 1.20.4, and 26.1. Data being present does not imply that the protocol client,
packet codecs, world decoder, or bot supports that version end to end. `PalettedContainer` decodes
modern layouts, but its existence alone does not establish full modern chunk support.

## Shapes

`ShapeTable` precomputes `AABB` tuples:

```python
mc.shapes.boxes_for("stone")  # full cube
mc.shapes.boxes_for("air")  # ()
mc.collision_boxes(mc.blocks.state_id("stone"))
```

`blocks` values in `blockCollisionShapes.json` may be a single shape id or a metadata-indexed list.
`McData.collision_boxes(state_id)` resolves through the loaded registry and shape table; the result
depends on the data for the selected version.

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

`version_key("1.8.9") == "1.8"`, `protocol_for("1.8.9") == 47`, and
`version_for_protocol(47) == "1.8"`. `version_key()` normalizes selected aliases and otherwise
returns a parseable version key; the loader reports when corresponding files are unavailable.
