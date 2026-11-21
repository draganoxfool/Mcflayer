# Models

`pyflayer.models` contains pure, frozen value types: no I/O, no asyncio, no registries.

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

- `AABB(min_x, …, max_z)` — intersection, containment, translation, expansion.
- `Dimension`, `GameMode`, `Face`, `Hand`, `Difficulty`, `Pose`, `ConnectionState`.
- `ChatComponent` — parses a JSON string, mapping or list; flatten with `plain_text()`;
  translation keys can be supplied for tests and tooling.
- `ItemStack(item_id, name, count, damage, nbt)` with `.empty`.
- `models.protocols`: `WorldReader`, `ActionHost`, `PacketSink`, `Dispatcher`, `BlockMatcher`.
  Upper layers depend on these, never on concrete classes (ADR-2).

## Chat example

```python
from pyflayer.models import ChatComponent

motd = ChatComponent.parse({"text": "Hello ", "extra": [{"text": "world", "bold": True}]})
assert motd.plain_text() == "Hello world"
```
