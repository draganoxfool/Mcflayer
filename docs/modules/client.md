# Protocol client

`ProtocolClient` owns one protocol connection, including login negotiation and decoded Play packet
iteration. It does not maintain bot, world, or entity state.

## Usage

```python
from pyflayer.protocol import ProtocolClient

client = ProtocolClient("play.pika-network.net", "Steve")
session = await client.connect()  # handshake -> login -> PLAY
try:
    async for packet in client.packets():
        if packet.name == "chat":
            print(packet.fields["message"])
finally:
    await client.close()
```

## What `connect()` does

1. loads `McData` and creates a lazily compiled packet registry;
2. opens the TCP connection (SRV when the port is 25565) and sends `set_protocol` with `nextState=2`;
3. runs `AuthProvider.login()` and sends Login Start;
4. handles the login loop:
   - `disconnect` → `LoginRejected(reason=ChatComponent)`;
   - `encryption_begin` → RSA PKCS#1 v1.5 for the shared secret and verify token, session-server
     join for online sessions, response sent in the clear, AES-CFB8 enabled at the next frame;
   - `compress` → applies the threshold (unless `use_compression=False`);
  - `success` → updates the session and switches the state machine to `PLAY`.

## Play packets

- `packets()` yields decoded `play/toClient` packets.
- Unknown packet ids are counted in `skipped_packets`, recorded in `unknown_packet_ids`, and
  represented internally by a packet with an `unknown_0x...` name; `packets()` drops that sentinel.
  Unsupported packet types are handled similarly. The 1.8 chunk-data and entity-metadata codecs are
  implemented; this does not establish support for those packet families on other versions.
- A `set_compression` packet received in Play updates the frame codec and is not yielded.
- Packet fields are plain dicts; `Packet` carries `name`, `fields`, `state`, `direction`, `raw_len`.

## Sending

```python
await client.send_chat("hello")
await client.send_packet("keep_alive", {"keepAliveId": 123})
```

`send_packet` is only legal in Play and raises `ProtocolError` otherwise.

## State machine

`client.state` is a `StateMachine`. Legal transitions are `handshaking → status|login`,
`login → configuration|play`, and `play ↔ configuration`; any active state can close. An illegal
transition raises `StateError` with `current` and `target` fields.
