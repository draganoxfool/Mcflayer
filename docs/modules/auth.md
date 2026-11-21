# Auth

`pyflayer.protocol.auth` supplies the identity used for Login Start and, for online-mode servers,
the session-server proof that follows the encryption request.

## Providers

| Provider | Use | Join behaviour |
|---|---|---|
| `OfflineAuth(name)` | Cracked/offline servers (PikaNetwork) | No-op |
| `MicrosoftAuth(...)` | Online-mode accounts | `sessionserver.mojang.com/session/minecraft/join` |
| `StaticAuth(session, online_join=False)` | Tests / a token cache you own | Optional |

All providers implement the `AuthProvider` Protocol and return a `Session(username, uuid,
access_token, xuid)`.

```python
from pyflayer.protocol.auth import OfflineAuth, MicrosoftAuth

session = await OfflineAuth("Steve").login()
print(session.uuid)   # b50ad385-...-style UUIDv3

auth = MicrosoftAuth(on_device_code=lambda code, uri: print(uri, code))
session = await auth.login()    # device code -> XBL -> XSTS -> Minecraft profile
```

## Offline UUID

The UUID is `UUIDv3("OfflinePlayer:<name>")`, matching the vanilla server, with the version and
RFC 4122 variant bits set. Names are validated against vanilla's rules (1–16 characters,
`[A-Za-z0-9_]`); failures raise `AuthError`.

## Server hash

`server_hash(server_id, shared_secret, public_key)` is a SHA-1 over the concatenation, formatted as
Java's signed big-integer hex (roughly half of all hashes start with `-`). The hash is computed and
the session join completes *before* the encrypted encryption response is sent, as the protocol
requires.

## Microsoft flow (not live-tested here)

Device code (`login.microsoftonline.com/consumers`) → Xbox Live user token → XSTS token for
`rp://api.minecraftservices.com/` → `login_with_xbox` → `/minecraft/profile`. Polling uses the
injected `Clock`; `authorization_pending` and `slow_down` are handled, and `invalid_grant`,
`invalid_client` and `expired_token` become `AuthError`s. A `refresh_token` can be supplied to skip
the interactive step. Tokens are kept in memory only.

> Limitation: no on-disk token cache yet, and the flow needs a real Microsoft account to verify.
