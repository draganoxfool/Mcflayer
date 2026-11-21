# Protodef compiler

`minecraft-data` describes packets as JSON. Interpreting that JSON per packet is too slow, so
`ProtocolCompiler` compiles every type into a small codec object with `read(reader, ctx)` and
`write(writer, value, ctx)`. Compilation is lazy per packet and cached.

## Packet registry

```python
from pyflayer.data import McData
from pyflayer.protocol import PacketRegistry

registry = PacketRegistry(McData.load("1.8.9"))

payload = registry.encode(
    "handshaking", "toServer", "set_protocol",
    {"protocolVersion": 47, "serverHost": "localhost",
     "serverPort": 25565, "nextState": 1},
)
# b'\x00\x2f\x09localhost\x63\xdd\x01'

packet = registry.decode("handshaking", "toServer", payload)
packet.name    # 'set_protocol'
packet.fields  # dict of decoded fields
```

- `codec(state, direction)` returns a `PacketCodec` exposing `ids`, `names`, `decode()`, `encode()`.
- Unknown packet ids raise `UnknownPacket` carrying the raw body; M1 policy is never fatal.
- Trailing bytes are rejected by default (`strict=True`); pass `strict=False` in diagnostics.
- `register_native(state, direction, name, codec)` installs a hand-written override (used by
  `protocol/native` in later milestones).

## Supported types

`varint`, `varlong`, `u8`–`u64`, `i8`–`i64`, `f32`, `f64`, `bool`, `UUID`, `pstring`/`string`,
`buffer`, `restBuffer`, `array` (count-by-type, count-by-field, fixed count), `container`, `switch`
(including default), `option`, `bitfield`, `bitflags`, `mapper`, `void`, `nbt`, `optionalNbt`,
`anonymousNbt`, `position`, `slot`, `entityMetadataLoop`.

Unsupported types raise `UnsupportedType` with state/direction/type and an extension-point hint —
never wrong bytes.

## Current compile coverage (1.8.9)

| State / direction | Compiled | Unsupported |
|---|---|---|
| handshaking / toServer | 2 / 2 | — |
| status / toServer | 2 / 2 | — |
| status / toClient | 2 / 2 | — |
| login / toServer | 2 / 2 | — |
| login / toClient | 4 / 4 | — |
| play / toServer | 26 / 26 | — |
| play / toClient | 74 / 74 | — |

All play packets compile for 1.8.9. The final gap was `entityMetadataLoop`; M3 added the native
codec in `protocol/native/entity_metadata.py`.

```python
report = registry.compiler.compile_state("play", "toClient")
report.ok             # True
report.compiled       # list[str] of 74 names
report.unsupported    # {}
```

## 1.8 specifics handled by the compiler

- `position` is a schema `bitfield` with X/Y/Z order, matching the pre-1.14 layout.
- `slot` resolves to the native `ItemStack` codec for 1.8–1.20.4, not the raw JSON container, so
  callers get typed items instead of `blockId`/`itemCount` dicts.
- `entityMetadataLoop` resolves to the native 1.8 codec; every play packet then compiles.
- `string` resolves through `pstring`, whose prefix counts UTF-8 bytes.
- `mapper` keys may be hex (`"0x1a"`) or decimal; decode returns names, encode accepts names or ids.

## Context handling

Container fields are decoded into the packet dict; a copy of the context is threaded to child
containers. `switch.compareTo` resolves against the sibling field of the same name, which covers
every 1.8 schema. `$context` switches used by some newer schemas require a native codec.

Anonymous fields (`anon: true`, seen in entity metadata) are merged into the parent dict when they
decode to a dict; otherwise they are stored under `__anon_N`.
