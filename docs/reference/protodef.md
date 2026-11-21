# `pyflayer.protocol.protodef`

The protodef compiler and packet registry. Converts `minecraft-data` protocol schemas into
executable Python codecs for reading and writing packets.

```python
from pyflayer.data import McData
from pyflayer.protocol import PacketRegistry
from pyflayer.protocol.protodef import PacketCodec, Packet, ProtocolCompiler
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## PacketRegistry

The version-scoped entry point. It builds a `PacketCodec` per state/direction lazily and exposes
name/id lookups. There is no module-level singleton registry and no `get()` method.

```python
from pyflayer.data import McData
from pyflayer.protocol import PacketRegistry

mc = McData.load("1.8.9")
registry = PacketRegistry(mc)

chat_id = registry.packet_id("play", "toClient", "chat")
print(chat_id, registry.packet_name("play", "toClient", chat_id))

payload = registry.encode("play", "toServer", "chat", {"message": "hello"})
packet = registry.decode("play", "toServer", payload)
print(packet.name, packet.fields)
```

| Method | Meaning |
|---|---|
| `codec(state, direction)` | Get/build the `PacketCodec` for one direction |
| `decode(state, direction, payload, *, strict=True)` | Decode a full payload (id + fields) |
| `encode(state, direction, name, fields)` | Encode a named packet |
| `packet_id(state, direction, name)` | Name → id |
| `packet_name(state, direction, packet_id)` | Id → name |
| `packet_names(state, direction)` | All known packet names |
| `compile_all(state, direction)` | Compile every packet; returns unsupported names/errors |
| `register_native(state, direction, name, codec)` | Install a native override |

`PacketRegistry` raises `MissingRegistryEntry` if a state/direction has no packet ids.

## PacketCodec

Binds one state/direction to its packet ids and compiler. `encode()` returns the full payload
including the packet id; `decode()` accepts that same payload.

```python
codec = registry.codec("play", "toClient")
print("chat" in codec)
packet = codec.decode(payload, strict=False)
```

`decode()` raises `UnknownPacket` for an unregistered id, `MalformedPacket` for bad fields, and
`UnsupportedType` when the schema uses a type the compiler does not implement.

## ProtocolCompiler

Compiles protocol types into cached codecs. Native packet overrides (chunk data, entity metadata,
slots) are passed in `native_packets`.

```python
from pyflayer.protocol.protodef import ProtocolCompiler

compiler = ProtocolCompiler(mc.protocol, mc.features)
codec = compiler.packet_codec("play", "toClient", "chat")
```

| Method | Meaning |
|---|---|
| `compile_type(spec, state, direction)` | Compile an inline type spec |
| `packet_codec(state, direction, name)` | Compile/cache one packet's field codec |
| `compile_state(state, direction)` | Compile a whole direction and return a `CompileReport` |

`CompileReport` has `compiled` (names), `unsupported` (name → reason), and `ok`.

## Packet

```python
from pyflayer.protocol.protodef import Packet

packet = Packet(
    name="chat",
    fields={"message": "hi"},
    state="play",
    direction="toClient",
)
```

Fields: `name`, `fields`, `state`, `direction`, and `raw_len`.

## Quick example

```python
from pyflayer.data import McData
from pyflayer.protocol import PacketRegistry

mc = McData.load("1.8.9")
registry = PacketRegistry(mc)
unsupported = registry.compile_all("play", "toClient")
print(f"unsupported packets: {sorted(unsupported)}")
```
