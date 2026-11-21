# Errors

`pyflayer.errors` is the only place library exceptions are defined (ADR-10). Every error derives
from `PyFlayerError` and carries structured fields, so callers never parse messages.

```
PyFlayerError
├── ProtocolError
│   ├── MalformedPacket(offset, packet)
│   ├── UnknownPacket(packet_id, raw)
│   ├── FramingError
│   ├── CompressionError
│   ├── StateError(current, target)
│   ├── UnsupportedVersion
│   └── UnsupportedType(type_name, state, direction)
├── ConnectionClosed(bytes_consumed, expected, reason)
├── AuthError
├── LoginRejected(reason)
├── KickedError(reason)
├── DataError
│   └── MissingRegistryEntry(registry, key)
├── WorldError
│   ├── ChunkNotLoaded(pos)
│   └── OutOfWorldBounds
├── ActionError
│   ├── ActionBusy, ActionPreempted, ActionCancelled, ActionFailed, LeaseRevoked
├── PathError
│   ├── NoPath(partial)
│   └── PathTimeout
└── ExtensionError
    ├── ExtensionNotLoaded, ExtensionAlreadyLoaded, ExtensionFailed
```

## Behaviour

- Errors are import-safe from every layer; `errors` is the bottom of the dependency graph.
- `MalformedPacket` always includes the reader offset when known, which makes fuzz failures
  reproducible.
- `UnknownPacket` retains the **raw payload after the packet id**. M1 never treats an unknown packet
  as fatal; the policy is the connection state machine's decision in M2.
- `CompressionError` distinguishes a lying length prefix, a zlib bomb, and trailing zlib data.

## Example

```python
from pyflayer.errors import MalformedPacket, ProtocolError

try:
    reader.read_varint()
except ProtocolError as exc:
    print(exc.fields)       # {'offset': 3}
```

!!! note "Known limitation"
    `FakeClock.advance()` raises a plain `ValueError` because it is a test helper, not library
    behaviour. No library code path raises built-in exceptions.
