# `pyflayer.data`

Data loading, version mapping, registries, and feature flags.

```python
from pyflayer.data import Features, McData, VersionInfo
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## McData

An immutable data snapshot for one version: registries, shapes, protocol schema and feature flags.
Only 1.8.9 data is vendored in this repository, but `load()` accepts any version present in the data
directory.

```python
from pyflayer.data import McData

mc = McData.load("1.8.9")
print(mc.version.protocol)   # 47
print(mc.version.key)        # "1.8"
print(mc.features.teleport_confirm)  # False
```

**Attributes**

| Attribute | Meaning |
|---|---|
| `version` | `VersionInfo` — data key, protocol, reported Minecraft version |
| `features` | `Features` for this version |
| `blocks`, `items`, `entities`, `biomes`, `effects`, `foods` | Registries |
| `shapes` | `ShapeTable` with collision boxes |
| `protocol` | Compiled protocol schema |

**Methods**

| Method | Meaning |
|---|---|
| `McData.load(version, *, edition="pc")` | Load (and cache) a version by string or protocol |
| `supports(feature)` | Shortcut for `features.supports(feature)` |
| `collision_boxes(state_id)` | Legacy 1.8 collision boxes for a state id |

`McData.load()` raises `UnsupportedVersion` for an unknown version and `DataError` for missing or
malformed data.

## Registries

Registries support lookup by name or numeric id and raise `MissingRegistryEntry` when absent.
`get()` returns `None` instead.

```python
stone = mc.blocks["stone"]            # minecraft:stone
assert stone.id == 1
assert mc.blocks[1].name == "stone"
assert mc.blocks.get("not_a_block") is None
assert mc.blocks.state_id("stone") == 16
```

## Features

`Features.for_version("1.8.9")` returns frozen capabilities. Protocol code asks these flags rather
than comparing version numbers directly.

```python
from pyflayer.data import Features

features = Features.for_version("1.8.9")
print(features.position_packed_xzy)  # False
print(features.teleport_confirm)     # False
print(features.supports("item_components"))  # False

modern = Features.for_version("1.20.6")
print(modern.item_components)        # True (protocol 766+)
```

| Flag | Meaning |
|---|---|
| `position_packed_xzy` | 1.14+ packed position order |
| `network_nbt_nameless` | 1.20.2+ nameless network NBT |
| `slot_item_id_varint` | 1.13+ VarInt item ids in slots |
| `item_components` | 1.20.5+ structured item components (protocol 766+) |
| `block_state_ids` | 1.13+ global block-state ids |
| `configuration_state` | 1.20.2+ configuration state |
| `chunk_batches` | 1.20.2+ chunk batch packets |
| `palette_non_spanning` | 1.16+ non-spanning palette packing |
| `login_start_uuid` | 1.20.2+ UUID in Login Start |
| `compression_supported` | Built-in compression (1.8+) |
| `teleport_confirm` | 1.9+ teleport id/confirm packets |

`supports(name)` returns `False` for unknown flag names; `as_dict()` returns only booleans.

## VersionInfo

```python
from pyflayer.data import VersionInfo

vi = VersionInfo(
    key="1.8",
    minecraft_version="1.8.8",
    protocol=47,
    major_version="1.8",
)
print(vi.release)  # (1, 8, 8)
```

**Attributes**

| Attribute | Type | Meaning |
|---|---|---|
| `key` | `str` | `minecraft-data` data key (`"1.8"`) |
| `minecraft_version` | `str` | Version reported by the data files (`"1.8.8"`) |
| `protocol` | `int` | Protocol version number |
| `major_version` | `str` | Version family (`"1.8"`) |
| `release` | `tuple[int, int, int]` | Parsed semantic release |

## Version helpers

```python
from pyflayer.data import version_for_protocol, version_key

version_key("1.8.9")        # "1.8"
version_key(47)             # "1.8"
version_for_protocol(47)    # "1.8"
```

Aliases map 1.8.x to the data key `1.8`. `version_key()` raises `UnsupportedVersion` for a protocol
with no data.

## Quick example

```python
from pyflayer.data import McData

mc = McData.load("1.8.9")
stone_id = mc.blocks.state_id("stone")
boxes = mc.collision_boxes(stone_id)
print(stone_id, boxes)
```
