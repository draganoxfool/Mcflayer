from __future__ import annotations

import hashlib

import pytest

from pyflayer.errors import AuthError
from pyflayer.protocol.auth.base import Session, StaticAuth
from pyflayer.protocol.auth.microsoft import MicrosoftAuth
from pyflayer.protocol.auth.offline import OfflineAuth, offline_uuid, validate_username
from pyflayer.protocol.auth.session_join import server_hash


def test_offline_uuid_matches_vanilla_vector() -> None:
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"
    assert OfflineAuth("Notch").username == "Notch"


async def test_offline_auth_returns_session_and_skips_join() -> None:
    auth = OfflineAuth("Steve")
    session = await auth.login()
    assert session.username == "Steve"
    assert session.uuid == offline_uuid("Steve")
    assert not session.online
    await auth.join(session, server_hash="anything")  # no-op, must not raise


def test_username_validation() -> None:
    assert validate_username("A_1") == "A_1"
    with pytest.raises(AuthError):
        validate_username("")
    with pytest.raises(AuthError):
        validate_username("x" * 17)
    with pytest.raises(AuthError):
        validate_username("bad name")


def test_server_hash_is_signed_sha1() -> None:
    digest = hashlib.sha1(b"secretkey").digest()
    expected = format(int.from_bytes(digest, "big", signed=True), "x")
    assert server_hash("secret", b"", b"key") == expected
    # A digest whose top bit is set is negative and therefore starts with '-'.
    assert server_hash("", b"", b"") == format(
        int.from_bytes(hashlib.sha1(b"").digest(), "big", signed=True), "x"
    )
    assert server_hash("", b"", b"").startswith("-")


async def test_static_auth() -> None:
    session = Session("Alex", "00000000-0000-0000-0000-000000000000")
    auth = StaticAuth(session)
    assert await auth.login() is session
    await auth.join(session, server_hash="x")


async def test_static_auth_online_join_requires_token() -> None:
    session = Session("Alex", "00000000-0000-0000-0000-000000000000")
    auth = StaticAuth(session, online_join=True)
    with pytest.raises(AuthError):
        await auth.join(session, server_hash="x")


class _Response:
    status_code = 200

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def json(self) -> dict[str, object]:
        return self._data


class _Client:
    def __init__(self, *, post: dict[str, object], get: dict[str, object]) -> None:
        self._post = post
        self._get = get

    async def post(self, *args: object, **kwargs: object) -> _Response:
        return _Response(self._post)

    async def get(self, *args: object, **kwargs: object) -> _Response:
        return _Response(self._get)


async def test_microsoft_xuid_comes_from_xsts_not_skin() -> None:
    client = _Client(
        post={
            "Token": "xsts-token",
            "DisplayClaims": {"xui": [{"uhs": "user-hash", "xid": "123456789"}]},
        },
        get={"name": "Alex", "id": "0" * 32, "skins": [{"id": "skin-id"}]},
    )
    auth = MicrosoftAuth()
    xsts = await auth._xsts(client, "xbl-token")
    assert xsts["xuid"] == "123456789"
    session = await auth._profile(client, "token", xuid=xsts["xuid"])
    assert session.xuid == "123456789"
    assert session.xuid != "skin-id"


async def test_microsoft_xsts_rejects_malformed_claims() -> None:
    client = _Client(post={"Token": "xsts-token", "DisplayClaims": "nope"}, get={})
    with pytest.raises(AuthError):
        await MicrosoftAuth()._xsts(client, "xbl-token")


async def test_microsoft_profile_rejects_bad_uuid() -> None:
    with pytest.raises(AuthError):
        await MicrosoftAuth()._profile(
            _Client(post={}, get={"name": "Alex", "id": "short"}), "token"
        )
    with pytest.raises(AuthError):
        await MicrosoftAuth()._profile(
            _Client(post={}, get={"name": "Alex", "id": "z" * 32}), "token"
        )
