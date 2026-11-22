# Transport

Framing, crypto, the TCP connection and server list ping.

## Framing and compression

```python
from pyflayer.protocol import FrameCodec

codec = FrameCodec()  # compression off
frame = codec.encode(payload)  # [length VarInt][payload]
assert codec.decode(frame[1:]) == payload

codec = FrameCodec(compression_threshold=256)
```

With compression enabled the body is:

```
[uncompressed length VarInt][zlib data]   # length > 0
[0][raw packet]                           # length == 0, must be below threshold
```

Limits and safety:

| Constant | Value | Meaning |
|---|---|---|
| `MAX_FRAME` | `2**21 - 1` | maximum frame body |
| `MAX_UNCOMPRESSED` | `2**23` | maximum declared uncompressed size |

The declared size is checked **before** inflating, and `decompressobj.decompress` is bounded to
`declared + 1`. A stream that would produce more raises `CompressionError`, so zlib bombs are
rejected without allocating the output. Lying lengths (too small/too large), trailing zlib data and
truncated streams all raise `CompressionError`.

`read_frame_async(reader, codec)` uses `readexactly`, so adversarial one-byte reads work; a peer that
closes mid-frame raises `FramingError` (or `ConnectionClosed` through `Connection`).

## AES-128-CFB8

```python
from pyflayer.protocol import CipherPair

enc, dec = CipherPair(shared_secret), CipherPair(shared_secret)
assert dec.decrypt(enc.encrypt(b"hello")) == b"hello"
```

Key and IV are both the shared secret, per the protocol. Encryption and decryption use independent
stream states, so enabling encryption at a frame boundary does not corrupt the other direction.

## Connection

```python
from pyflayer.protocol import Connection

async with await Connection.open("play.example.org") as conn:
    await conn.write_payload(payload)
    reply = await conn.read_payload()
    conn.set_compression(256)
    conn.enable_encryption(shared_secret)
```

- `asyncio.open_connection`, `TCP_NODELAY`, `drain()` backpressure, a single write lock.
- `resolve_address` attempts `_minecraft._tcp.<host>` lookup when SRV is enabled and the port is the
  default, then falls back to the original host and port if lookup fails.
- Reads and writes decrypt/frame automatically once enabled. A write to a closing connection raises
  `ConnectionClosed`.
- `read_timeout` is applied per frame with `asyncio.timeout`.

## Server List Ping

```bash
python -m pyflayer.protocol.status play.example.org
python -m pyflayer.protocol.status 127.0.0.1 --port 25565 --no-srv
```

```python
from pyflayer.protocol import ping

status = await ping("play.example.org", protocol="1.8.9")
print(status.version_name, status.online_players, status.motd, status.latency_ms)
```

`ServerStatus` carries the version, protocol, player counts/sample, MOTD as a `ChatComponent`, the
favicon (decoded via `.favicon_png`), latency and the raw JSON. Malformed JSON raises
`MalformedPacket`; malformed **optional** fields degrade to defaults. The ping/pong round trip is
measured with the injected `Clock`.

### Limitations

- Legacy (pre-1.7) `0xFE` server list ping is not implemented; 1.8.9 supports modern SLP.
- SRV records are ordered by priority and then descending weight; this is not the DNS SRV
  weighted-random selection algorithm.
- SRV resolution runs in a worker thread via `asyncio.to_thread` (sync DNS API).

## Tests

Loopback servers in `tests/test_framing.py` and `tests/test_status.py` exercise compression
boundaries, one-byte reads, mid-frame close, a full SLP round trip and malformed responses.
