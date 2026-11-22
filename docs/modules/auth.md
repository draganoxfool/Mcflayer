# Auth

`pyflayer.protocol.auth` supplies the session used for Login Start and the session-server join used
when a server requests online-mode encryption.

## Providers

| Provider | Use | `join()` behavior |
|---|---|---|
| `OfflineAuth(username)` | Offline-mode identity | No-op |
| `MicrosoftAuth(...)` | Microsoft/Xbox/Minecraft account flow | Session-server join |
| `StaticAuth(session, online_join=False)` | Caller-supplied session | Optional session-server join |

All providers implement the `AuthProvider` Protocol and return a `Session(username, uuid,
access_token, xuid)`.

```python
from pyflayer.protocol.auth import OfflineAuth, MicrosoftAuth

session = await OfflineAuth("Steve").login()
print(session.uuid)  # b50ad385-...-style UUIDv3

auth = MicrosoftAuth(on_device_code=lambda code, uri: print(uri, code))
session = await auth.login()  # device code -> XBL -> XSTS -> Minecraft profile
```

## Offline UUID

`offline_uuid(username)` returns UUIDv3 over `OfflinePlayer:<name>` and sets the version and RFC 4122
variant bits. `OfflineAuth` validates names as 1–16 ASCII letters, digits, or underscores; invalid
names raise `AuthError`.

## Server hash

`server_hash(server_id, shared_secret, public_key)` is a SHA-1 over the concatenation, formatted as
Java's signed big-integer hex (roughly half of all hashes start with `-`). The hash is computed and
the session join completes *before* the encrypted encryption response is sent, as the protocol
requires.

## Microsoft flow (not live-tested here)

The provider implements the consumer device-code flow, Xbox Live authentication, XSTS authorization,
Minecraft Services login, and profile retrieval. Polling uses the injected `Clock`; recognized
pending/slow-down responses are handled, and selected OAuth errors become `AuthError`. A
`refresh_token` can be supplied instead of starting device authorization. The provider updates its
refresh token in memory and does not persist it to disk.

> Limitation: the flow has not been verified here with a live Microsoft account.
