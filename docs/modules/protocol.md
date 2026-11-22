# Protocol primitives (`pyflayer.protocol`)

These modules turn bytes into values and values into bytes. They know nothing about game semantics
(ADR-3).

## VarInt / VarLong

```python
from pyflayer.protocol import encode_varint, decode_varint

encode_varint(-1)  # b'\xff\xff\xff\xff\x0f'
decode_varint(b"\xac\x02")  # (300, 2)
```

- Signed 32-bit VarInt (max 5 bytes) and signed 64-bit VarLong (max 10 bytes).
- Over-long or truncated encodings raise `MalformedPacket`.
- `read_varint(reader)` reads one byte at a time from an asyncio stream, so split TCP reads work.
- `read_varint_sync` exists for offline tools only.

## PacketReader / PacketWriter

`PacketReader` is a bounds-checked `memoryview` cursor; `PacketWriter` builds bytes.

```python
from pyflayer.protocol import PacketReader, PacketWriter

w = PacketWriter()
w.write_varint(7)
w.write_string("hello")
w.write_position(BlockPos(1, 64, -3))

r = PacketReader(w.to_bytes())
assert r.read_varint() == 7
assert r.read_string() == "hello"
assert r.read_position() == BlockPos(1, 64, -3)
r.ensure_finished()  # strict by default
```

Primitives: `u8/i8/u16/i16/u32/i32/u64/i64/f32/f64`, `bool`, VarInt/VarLong, strings, UUID, packed
position, NBT, slots, BitSet, plus `read_optional`/`read_array` for protodef.

### Strings

The wire prefix counts **UTF-8 bytes**; the decoded string is limited to 32,767 characters.
Astral characters (4-byte UTF-8) are one character but four prefix bytes. Invalid/overlong UTF-8 and
a decoded length over the limit raise `MalformedPacket`.

!!! warning "Found in the wild"
    An early implementation used a UTF-16 code-unit count. A real Server List Ping against
    `play.pika-network.net` (Velocity) returned a MOTD containing `§` colour codes and exposed the
    bug: the declared length was 9,671 bytes while the decoded string was 9,669 UTF-16 units. The
    byte-count behaviour is what the vanilla `FriendlyByteBuf` does.

### Positions

- 1.8–1.13: `x << 38 | y << 26 | z` (26/12/26 bits).
- 1.14+: `x << 38 | z << 12 | y`.

`PacketReader.read_position()` selects the layout from `Features.position_packed_xzy`, and the
low-level functions accept an explicit flag.

### Slots

- 1.8–1.12: `i16 item_id` (`-1` empty), `i8 count`, `i16 damage`, named NBT.
- 1.13–1.20.4: `VarInt item_id` (`0` empty), `i8 count`, NBT (nameless from 1.20.2).
- 1.20.5+: structured components deliberately raise `UnsupportedType`; the extension point is
  `protocol/native/slot_components`.

## NBT

Supported tags: Byte, Short, Int, Long, Float, Double, ByteArray, String, List, Compound, IntArray,
LongArray. Two roots:

```python
from pyflayer.protocol.types.nbt import read_named_nbt, read_unnamed_nbt, write_named_nbt

raw = write_named_nbt("root", {"Level": 1, "Items": [...]})
named = read_named_nbt(PacketReader(raw))
```

- Classic named root for 1.8.9; nameless network root for 1.20.2+ (`Features` decides).
- Lists keep their element tag type (`NBTList(tag_type, items)`) so an empty list can be round-tripped.
- Compounds are `dict[str, object]`; int/long arrays are tuples; byte arrays are `bytes`.
- Depth limit 512 and negative/oversized lengths are rejected before allocation.
- NBT names and string payloads use Java Modified UTF-8, including its UTF-16-code-unit handling
  for supplementary characters. Ordinary protocol strings use their separate standard UTF-8 codec.

## UUID / BitSet

`read_uuid`/`write_uuid` use the 16 raw bytes; helpers split into signed 64-bit halves for protodef.
BitSets are a VarInt count of big-endian 64-bit longs; the read limit defaults to 1024 longs.

## Tests

`tests/test_varint.py`, `tests/test_buffer.py`, `tests/test_nbt.py` cover golden vectors, negatives,
5/10-byte limits, split reads, astral strings, overlong UTF-8, position boundaries, slot variants,
depth bombs and strict trailing-byte handling.
