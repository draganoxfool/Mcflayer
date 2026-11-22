# Errors

`pyflayer.errors` defines the package exception hierarchy. Its exceptions derive from
`PyFlayerError` and expose a `fields` mapping for additional context; APIs may also raise built-in
exceptions for invalid arguments and runtime misuse.

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

- `MalformedPacket` may include an `offset`, packet name, and codec-specific context when available.
- `UnknownPacket` carries `packet_id` and the raw packet body after the id. Whether an unknown
  packet is skipped or rejected depends on the caller and protocol state.
- `CompressionError` is used for invalid compressed lengths, malformed/truncated zlib streams, and
  output that does not match the declared size.

## Example

```python
from pyflayer.errors import MalformedPacket, ProtocolError

try:
    reader.read_varint()
except ProtocolError as exc:
  print(exc.fields.get("offset"))
```

!!! note "Known limitation"
    Not every error condition uses a `PyFlayerError` subclass. For example, invalid values in
    constructors or helper arguments can raise `ValueError` or `TypeError`.
