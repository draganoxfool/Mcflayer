# `pyflayer.protocol.auth`

Authentication providers for Minecraft login: offline mode, Microsoft device flow, static
sessions, and the Mojang session-server join.

```python
from pyflayer.protocol.auth import AuthProvider, MicrosoftAuth, OfflineAuth, Session, StaticAuth
```

## Version constants

The package is distributed on PyPI as **`mcflayer`**; the import name is **`pyflayer`**.

::: pyflayer
    options:
      members: [__version__, PROTOCOL_VERSION, REFERENCE_VERSION]
      show_root_heading: false
      show_root_toc_entry: false
      show_attribute_values: true

## Session

A frozen identity used for one login.

```python
from pyflayer.protocol.auth import Session

session = Session(
    username="Steve",
    uuid="b50ad385-829d-3141-a216-7e7d7539ba7f",
    access_token=None,
    xuid=None,
)
print(session.online)  # False
print(session.uuid_no_dashes)  # b50ad385829d3141a2167e7d7539ba7f
```

| Attribute | Meaning |
|---|---|
| `username` | Name sent in Login Start |
| `uuid` | Canonical dashed UUID |
| `access_token` | Minecraft services token for online mode, or `None` |
| `xuid` | Xbox user id from XSTS, when known |
| `online` | `True` when `access_token` is present |
| `uuid_no_dashes` | UUID in the sessionserver profile-id format |

## AuthProvider

The protocol implemented by all providers.

```python
class MyAuth:
    async def login(self) -> Session: ...

    async def join(self, session: Session, *, server_hash: str) -> None: ...
```

| Method | Meaning |
|---|---|
| `login()` | Async. Obtain or refresh the session |
| `join(session, *, server_hash)` | Async. Prove ownership to the session server (or no-op offline) |

## OfflineAuth

Offline-mode authentication. The UUID is `UUIDv3("OfflinePlayer:<name>")`, matching the vanilla
server, with the version and RFC 4122 variant bits set. Names are validated against vanilla's
rules (1–16 characters, `[A-Za-z0-9_]`); invalid names raise `AuthError`.

```python
from pyflayer.protocol.auth import OfflineAuth

auth = OfflineAuth("Steve")
session = await auth.login()
# {"username": "Steve", "uuid": "...", "access_token": None}
await auth.join(session, server_hash="anything")  # no-op
```

## MicrosoftAuth

Microsoft device-code flow for online-mode accounts. The default constructor uses the bundled
Azure client id; pass `client_id` to use your own app registration.

```python
from pyflayer.protocol.auth import MicrosoftAuth

auth = MicrosoftAuth(on_device_code=lambda code, uri: print(uri, code))
session = await auth.login()
```

The flow is: Microsoft OAuth device code → Xbox Live user token → XSTS token for
`rp://api.minecraftservices.com/` → Minecraft `login_with_xbox` → `/minecraft/profile`. Polling
uses the injected `Clock`; `authorization_pending` and `slow_down` are handled. The returned
`Session.xuid` comes from the XSTS `DisplayClaims.xui[0].xid` field, **not** the skin id in the
Minecraft profile. Tokens are kept in memory only; `refresh_token` skips the interactive step.

`join()` calls `sessionserver.mojang.com/session/minecraft/join` using the token.

## StaticAuth

Returns a pre-obtained session, for tests or an external token cache.

```python
from pyflayer.protocol.auth import Session, StaticAuth

session = Session("Alex", "00000000-0000-0000-0000-000000000000")
auth = StaticAuth(session)
assert await auth.login() is session
```

`StaticAuth(session, online_join=True)` also calls the Mojang session server; it raises `AuthError`
when the session has no access token.

## Server hash

`server_hash(server_id, shared_secret, public_key)` is a SHA-1 over the concatenation, formatted as
Java's signed big-integer hex (roughly half of all hashes start with `-`). The session join
completes *before* the encrypted encryption response is sent, as the protocol requires.

```python
from pyflayer.protocol.auth import server_hash

digest = server_hash("", shared_secret, server_public_key_der)
```

## Limitations

- No on-disk token cache.
- The Microsoft flow needs a real Microsoft account to exercise end-to-end; the HTTP chain is
  covered with injected clients rather than a live account in this repository.
