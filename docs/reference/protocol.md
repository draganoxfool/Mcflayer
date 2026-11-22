# `pyflayer.protocol`

Protocol package exports for transport, packet codecs, state tracking, and the low-level client.
For authentication, use `pyflayer.protocol.auth`; for server status, use
`pyflayer.protocol.status`.

::: pyflayer.protocol
    options:
      members:
        - CipherPair
        - Connection
        - ConnectionState
        - FrameCodec
        - Packet
        - PacketCodec
        - PacketReader
        - PacketRegistry
        - PacketWriter
        - ProtocolClient
        - ProtocolCompiler
        - ServerStatus
        - StateMachine
        - decode_varint
        - decode_varlong
        - encode_varint
        - encode_varlong
        - ping
        - resolve_address
      show_root_heading: false
      show_root_toc_entry: false

::: pyflayer.protocol.client.ProtocolClient

::: pyflayer.protocol.connection.Connection

::: pyflayer.protocol.status.ping

<!--

Low-level protocol types: connection, framing, packet codec, state machine, and client.

```python
from pyflayer.protocol import Connection, Packet, PacketReader, PacketRegistry, ProtocolClient
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Connection

The raw asyncio stream wrapper. It handles framing, compression, encryption, and state
transitions; most users should use `ProtocolClient` instead of constructing it directly.

```python
from pyflayer.protocol import Connection

# Usually created by ProtocolClient.connect():
# Connection(reader, writer, clock=clock)
```

| Attribute / method | Meaning |
|---|---|
| `read_payload()` | Read one uncompressed packet payload |
| `write_payload(payload)` | Frame and write one payload |
| `set_compression(threshold)` | Enable/disable zlib framing |
| `enable_encryption(secret)` | Switch to AES-128-CFB8 |
| `close()` | Close the socket |

## Packet

A decoded packet: a name, a field mapping, and the state/direction it came from.

```python
from pyflayer.protocol import Packet

packet = Packet(name="chat", fields={"message": "hi"}, state="play", direction="toClient")
print(packet.name, packet.fields)
```

| Attribute | Type | Meaning |
|---|---|---|
| `name` | `str` | Packet name, e.g. `"position"` |
| `fields` | `dict[str, Any]` | Decoded fields |
| `state` | `str` | Protocol state |
| `direction` | `str` | `"toClient"` or `"toServer"` |
| `raw_len` | `int` | Wire payload length |

## PacketRegistry

Maps packet names and ids to codecs for one `McData` snapshot. Build one per version; it lazily
compiles each state/direction.

```python
from pyflayer.data import McData
from pyflayer.protocol import PacketRegistry

mc = McData.load("1.8.9")
reg = PacketRegistry(mc)
print(reg.packet_id("play", "toClient", "chat"))
print(reg.packet_name("play", "toClient", 0x02))
```

| Method | Meaning |
|---|---|
| `decode(state, direction, payload, *, strict=True)` | Decode one payload |
| `encode(state, direction, name, fields)` | Encode a named packet |
| `packet_id(state, direction, name)` | Look up an id |
| `packet_name(state, direction, packet_id)` | Look up a name |
| `packet_names(state, direction)` | All known names |
| `compile_all(state, direction)` | Compile every packet and report unsupported schemas |
| `register_native(...)` | Install a native codec override |

## FrameCodec

Length-prefix and compression handling for one direction. `encode()` adds the outer VarInt length;
`decode()` consumes a frame body **without** that prefix.

```python
from pyflayer.protocol import FrameCodec, decode_varint

codec = FrameCodec(compression_threshold=-1)
frame = codec.encode(b"\x00hello")
length, offset = decode_varint(frame)
payload = codec.decode(frame[offset : offset + length])
```

Use `read_frame_async()` / `write_frame_async()` from `pyflayer.protocol.framing` when working
directly with asyncio readers and writers.

## StateMachine

Tracks `handshaking → status/login → play` and validates transitions. The method is `transition`,
not `transit`.

```python
from pyflayer.models import ConnectionState
from pyflayer.protocol import StateMachine

sm = StateMachine()
sm.transition(ConnectionState.LOGIN)
sm.transition(ConnectionState.PLAY)
```

## ProtocolClient

The main low-level client. It owns the socket, registry, authentication, and packet stream.

```python
from pyflayer.protocol import ProtocolClient

client = ProtocolClient(
    "play.pika-network.net",
    "Steve",
    port=25565,
    version="1.8.9",
    use_srv=True,
)
session = await client.connect()
print(session.username, client.protocol)
await client.close()
```

`ProtocolClient(host, username=None, *, port=25565, version="1.8.9", auth=None, use_srv=True,
clock=None, connect_timeout=10.0, read_timeout=None, use_compression=True)`. If `auth` is omitted,
an `OfflineAuth(username)` is created, so `username` is required in that case.

**Key attributes / methods**

| Member | Meaning |
|---|---|
| `connect()` | Connect, authenticate, and return the `Session` |
| `close()` | Close the connection |
| `packets()` | Async iterator of Play packets |
| `send_packet(name, fields)` | Send a raw Play packet |
| `send_chat(line)` | Send a chat packet |
| `skipped_packets` | Count of unknown/unsupported packets |
| `unknown_packet_ids` | Ids that had no codec |

`packets()` applies compression changes and **drops** unknown/unsupported placeholder packets
(they are still counted in `skipped_packets`). It stops when the connection closes and raises
`ConnectionClosed` if the close is an error.

## Server list ping

```python
import asyncio
import pyflayer

status = asyncio.run(pyflayer.ping("play.pika-network.net"))
print(status.version_name, status.online_players, status.latency_ms)
```

## Quick example

```python
import asyncio

from pyflayer.protocol import ProtocolClient


async def main() -> None:
    client = ProtocolClient("play.pika-network.net", "Steve", version="1.8.9")
    await client.connect()
    try:
        async for packet in client.packets():
            print(f"Received: {packet.name}")
            if packet.name == "chat":
                await client.send_chat("hello")
                break
    finally:
        await client.close()


asyncio.run(main())
```
