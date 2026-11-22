# Models

`pyflayer.models` contains value types and structural protocols shared across package layers.

## Coordinates

| Type | Fields | Notes |
|---|---|---|
| `Vec3` | `x, y, z: float` | Arithmetic, dot/cross, length, normalize, `floored()` |
| `BlockPos` | `x, y, z: int` | `.chunk`, `.section`, local coordinates, `to_vec3()` |
| `ChunkPos` | `x, z: int` | 16×16 column |
| `SectionPos` | `x, y, z: int` | 16³ section |

`BlockPos` uses floor division / bit shifts, so negative coordinates are correct:
`BlockPos(-1, 0, 16).chunk == ChunkPos(-1, 1)`.

## Other values

- `AABB(min_x, min_y, min_z, max_x, max_y, max_z)` — intersection, containment, translation, and expansion.
- `Dimension`, `GameMode`, `Face`, `Hand`, `Difficulty`, `Pose`, `ConnectionState`.
- `ChatComponent` — parses a JSON string, mapping or list; flatten with `plain_text()`;
  translation keys can be supplied for tests and tooling.
- `ItemStack(item_id, name, count, damage, nbt)` with `.empty`.
- `models.protocols` defines interfaces used by world, actions, packet, and dispatch code. These
  protocols describe compatible object surfaces; they do not imply that every caller uses only
  those abstractions.

## Chat example

```python
from pyflayer.models import ChatComponent

motd = ChatComponent.parse({"text": "Hello ", "extra": [{"text": "world", "bold": True}]})
assert motd.plain_text() == "Hello world"
```
