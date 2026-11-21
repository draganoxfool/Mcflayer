"""Microsoft authentication (device-code flow).

Implements the chain a vanilla client uses for online mode:

1. OAuth device-code flow against ``login.microsoftonline.com`` (no browser automation,
   no password);
2. Xbox Live user authentication (XBL);
3. XSTS authorization for the Minecraft relying party;
4. ``login_with_xbox`` for a Minecraft services access token;
5. ``/minecraft/profile`` for the name and UUID.

The public Mojang launcher client id is used by default, matching other open-source clients. A
refresh token can be supplied to skip the interactive steps; tokens are not written to disk here.

Examples:
    >>> async def show(code, uri): print(f"Go to {uri} and enter {code}")
    >>> auth = MicrosoftAuth(on_device_code=show)
    >>> session = await auth.login()  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.errors import AuthError
from pyflayer.protocol.auth.base import Session
from pyflayer.protocol.auth.session_join import join_session

__all__ = ["DEFAULT_CLIENT_ID", "DeviceCode", "MicrosoftAuth"]

DEFAULT_CLIENT_ID = "00000000402b5328"
DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
SCOPE = "XboxLive.signin offline_access"

DeviceCodeCallback = Callable[[str, str], Awaitable[None] | None]


class DeviceCode:
    """A pending device-code authorization."""

    __slots__ = ("device_code", "expires_in", "interval", "user_code", "verification_uri")

    def __init__(self, data: dict[str, Any]) -> None:
        self.user_code = str(data.get("user_code", ""))
        self.verification_uri = str(data.get("verification_uri", "https://microsoft.com/link"))
        self.device_code = str(data.get("device_code", ""))
        self.interval = int(data.get("interval", 5) or 5)
        self.expires_in = int(data.get("expires_in", 900) or 900)


class MicrosoftAuth:
    """Auth provider using the Microsoft/Xbox/Minecraft chain.

    Args:
        client_id: Azure application id to authenticate with.
        on_device_code: Called with ``(user_code, verification_uri)`` so the user can authorize.
        refresh_token: Existing refresh token, skipping the device-code step.
        clock: Injected clock used for polling (deterministic in tests).
        timeout: HTTP timeout in seconds.
        client: Optional shared HTTP client.
    """

    __slots__ = (
        "_access_token",
        "client",
        "client_id",
        "clock",
        "on_device_code",
        "refresh_token",
        "timeout",
    )

    def __init__(
        self,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        on_device_code: DeviceCodeCallback | None = None,
        refresh_token: str | None = None,
        clock: Clock | None = None,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.on_device_code = on_device_code
        self.refresh_token = refresh_token
        self.clock = clock or MonotonicClock()
        self.timeout = timeout
        self.client = client
        self._access_token: str | None = None

    # ------------------------------------------------------------------ public
    async def login(self) -> Session:
        """Run the interactive flow (or the refresh-token shortcut) and return a session."""
        try:
            if self.client is not None:
                return await self._login(self.client)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._login(client)
        except httpx.HTTPError as exc:
            raise AuthError("Microsoft authentication request failed", reason=str(exc)) from exc

    async def join(self, session: Session, *, server_hash: str) -> None:
        """Join the Mojang session server for this connection."""
        await join_session(session, server_hash, client=self.client, timeout=self.timeout)

    # ------------------------------------------------------------------ internals
    async def _login(self, client: httpx.AsyncClient) -> Session:
        token_data = await self._oauth_token(client)
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AuthError(
                "Microsoft OAuth response is missing an access token", response=token_data
            )
        self._access_token = access_token
        self.refresh_token = str(token_data.get("refresh_token", "")) or self.refresh_token
        xbl = await self._xbox_user(client, self._access_token)
        xbl_token = xbl.get("Token")
        if not isinstance(xbl_token, str) or not xbl_token:
            raise AuthError("Xbox Live response is missing a token", response=xbl)
        xsts = await self._xsts(client, xbl_token)
        identity = f"XBL3.0 x={xsts['uhs']};{xsts['token']}"
        minecraft_token = await self._minecraft_token(client, identity)
        return await self._profile(client, minecraft_token, xuid=xsts["xuid"])

    async def _oauth_token(self, client: httpx.AsyncClient) -> dict[str, Any]:
        if self.refresh_token:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "scope": SCOPE,
                },
            )
            return _json_or_auth_error(response, "token refresh failed")

        response = await client.post(
            DEVICE_CODE_URL, data={"client_id": self.client_id, "scope": SCOPE}
        )
        code = DeviceCode(_json_or_auth_error(response, "device-code request failed"))
        if self.on_device_code is not None:
            result = self.on_device_code(code.user_code, code.verification_uri)
            if asyncio.iscoroutine(result):
                await result

        deadline = self.clock.monotonic() + code.expires_in
        interval = max(1, code.interval)
        while self.clock.monotonic() < deadline:
            await self.clock.sleep(interval)
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": code.device_code,
                },
            )
            try:
                data = _json_or_auth_error(response, "device-code poll failed", allow_pending=True)
            except _Pending:
                continue
            except _SlowDown:
                interval = min(interval + 5, 60)
                continue
            return data
        raise AuthError("device-code authorization expired", user_code=code.user_code)

    async def _xbox_user(self, client: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
        response = await client.post(
            XBL_URL,
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={access_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            headers={"Accept": "application/json", "x-xbl-contract-version": "1"},
        )
        return _json_or_auth_error(response, "Xbox Live authentication failed")

    async def _xsts(self, client: httpx.AsyncClient, xbl_token: str) -> dict[str, Any]:
        response = await client.post(
            XSTS_URL,
            json={
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            headers={"Accept": "application/json", "x-xbl-contract-version": "1"},
        )
        data = _json_or_auth_error(response, "XSTS authorization failed")
        display = data.get("DisplayClaims")
        claims = display.get("xui") if isinstance(display, dict) else None
        first = claims[0] if isinstance(claims, list) and claims else None
        uhs = first.get("uhs") if isinstance(first, dict) else None
        xuid = first.get("xid") if isinstance(first, dict) else None
        if not uhs or not data.get("Token"):
            raise AuthError("XSTS response missing token or user hash", response=data)
        return {
            "token": str(data["Token"]),
            "uhs": str(uhs),
            "xuid": str(xuid) if xuid is not None and str(xuid) else None,
        }

    async def _minecraft_token(self, client: httpx.AsyncClient, identity: str) -> str:
        response = await client.post(
            MC_LOGIN_URL,
            json={"identityToken": identity},
            headers={"Accept": "application/json"},
        )
        data = _json_or_auth_error(response, "Minecraft login failed")
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError("Minecraft login returned no access token", response=data)
        return token

    async def _profile(
        self, client: httpx.AsyncClient, access_token: str, *, xuid: str | None = None
    ) -> Session:
        response = await client.get(
            MC_PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        data = _json_or_auth_error(response, "Minecraft profile request failed")
        name = data.get("name")
        player_id = data.get("id")
        if not isinstance(name, str) or not isinstance(player_id, str):
            raise AuthError("Minecraft profile is missing name or id", response=data)
        if len(player_id) != 32:
            raise AuthError("Minecraft profile id is not 32 hex digits", response=data)
        try:
            int(player_id, 16)
        except ValueError as exc:
            raise AuthError("Minecraft profile id is not hexadecimal", response=data) from exc
        dashed = (
            f"{player_id[0:8]}-{player_id[8:12]}-{player_id[12:16]}-"
            f"{player_id[16:20]}-{player_id[20:32]}"
        )
        return Session(name, dashed, access_token=access_token, xuid=xuid)


class _Pending(Exception):
    """Device-code authorization still pending."""


class _SlowDown(Exception):
    """Device-code poll interval must increase."""


def _json_or_auth_error(
    response: httpx.Response, message: str, *, allow_pending: bool = False
) -> dict[str, Any]:
    if response.status_code >= 400:
        try:
            data = response.json()
        except ValueError:
            data = {}
        error = data.get("error") if isinstance(data, dict) else None
        if allow_pending and error == "authorization_pending":
            raise _Pending
        if allow_pending and error == "slow_down":
            raise _SlowDown
        if error == "expired_token":
            raise AuthError("device-code authorization expired", error=error)
        if error in {"invalid_grant", "invalid_client"}:
            raise AuthError(
                "Microsoft rejected the credentials",
                error=error,
                description=data.get("error_description"),
            )
        raise AuthError(message, status=response.status_code, error=error)
    try:
        data = response.json()
    except ValueError as exc:
        raise AuthError(f"{message}: response was not JSON") from exc
    if not isinstance(data, dict):
        raise AuthError(f"{message}: response was not an object")
    return data
