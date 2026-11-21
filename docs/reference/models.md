# `pyflayer.models`

Core data types used throughout PyFlayer: positions, chat components, items, and enums.

```python
from pyflayer.models import Vec3, BlockPos, ChatComponent, ItemStack, Dimension, GameMode
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [REFERENCE_VERSION, PROTOCOL_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Vec3

An immutable 3D vector used for positions, dimensions and velocities.

```python
from pyflayer.models import Vec3

p = Vec3(1.5, 64.0, 2.5)
print(p.x, p.y, p.z)  # 1.5 64.0 2.5
print(p.floored())     # BlockPos(1, 64, 2)
```

| Attribute / method | Meaning |
|---|---|
| `x`, `y`, `z` | Components |
| `+`, `-`, `*`, `/` | Component-wise arithmetic |
| `dot(other)`, `cross(other)` | Vector products |
| `length()`, `normalize()` | Magnitude and unit vector |
| `floored()` | Floor each component and return `BlockPos` |

## BlockPos

Integer block coordinates.

```python
from pyflayer.models import BlockPos

bp = BlockPos(0, 64, 0)
print(bp.chunk)       # ChunkPos(0, 0)
print(bp.local_x())   # 0
print(bp.to_vec3())   # Vec3(0.5, 64.5, 0.5)
```

`ChunkPos` and `SectionPos` are the chunk-column and 16³-section coordinates.

## ChatComponent

A normalized chat component. Prefer `parse()` over constructing nested components by hand.

```python
from pyflayer.models import ChatComponent

component = ChatComponent.parse(
    {"text": "Hello ", "extra": [{"text": "world", "color": "gold"}]}
)
print(component.plain_text())  # "Hello world"
print(component.extra[0].color)  # "gold"
```

| Attribute | Type | Meaning |
|---|---|---|
| `text` | `str` | Literal text |
| `translate` | `str \| None` | Translation key |
| `with_args` | `tuple[ChatComponent, ...]` | Translation arguments |
| `extra` | `tuple[ChatComponent, ...]` | Child components |
| `color` | `str \| None` | Legacy color name |
| `bold`, `italic`, `underlined`, `strikethrough`, `obfuscated` | `bool` | Formatting flags |

| Method | Meaning |
|---|---|
| `ChatComponent.parse(raw)` | Parse JSON text, a mapping or a list |
| `plain_text(*, translate=None)` | Flatten to text, optionally translating keys |
| `to_json()` | Serialize to a minimal JSON component mapping |

`chat_component_from_json()` and `plain_text_from_json()` are convenience helpers for raw JSON.

## ItemStack

An immutable item stack. `count <= 0` or `item_id <= 0` means empty (`0` is air in 1.13+ and `-1`
is empty in 1.8).

```python
from pyflayer.models import ItemStack

stack = ItemStack(item_id=1, name="minecraft:stone", count=64)
print(stack.empty)              # False
print(stack.with_count(1).count)  # 1
```

| Attribute | Type | Meaning |
|---|---|---|
| `item_id` | `int` | Numeric item/registry id; `0`/`-1` empty |
| `name` | `str \| None` | Namespaced item name when known |
| `count` | `int` | Stack size |
| `damage` | `int` | Legacy damage/metadata |
| `nbt` | `dict \| None` | Raw NBT payload, treated as read-only |
| `empty` | `bool` | `count <= 0` or `item_id <= 0` |

## Dimension

Logical dimension identifiers (`StrEnum`).

```python
from pyflayer.models import Dimension

print(Dimension.OVERWORLD)  # "overworld"
print(Dimension.NETHER)     # "the_nether"
print(Dimension.END)        # "the_end"
```

The play protocol uses numeric dimension ids; `Dimension` is the version-independent name used by
the world layer.

## GameMode

Vanilla wire values (`IntEnum`).

| Value | Wire value |
|---|---|
| `SURVIVAL` | 0 |
| `CREATIVE` | 1 |
| `ADVENTURE` | 2 |
| `SPECTATOR` | 3 |

## Quick example

```python
import asyncio

from pyflayer import Bot
from pyflayer.models import Vec3


async def main() -> None:
    bot = Bot("Steve", host="play.pika-network.net")
    await bot.connect()
    print(f"Position: {bot.position}")

    @bot.event
    async def on_spawn(event):
        print(f"Spawned at {event.position}")

    await bot.run()


asyncio.run(main())
```

`Vec3` is also re-exported by `pyflayer.models` and `pyflayer`.
