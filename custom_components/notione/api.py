"""Thin async client for the unofficial notiOne API."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    API_ACCEPT,
    CLIENT_BASIC_AUTH,
    DEVICECONFIG_URL,
    DEVICELIST_URL,
    LOGIN_URL,
    SCOPE,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# Re-login this many seconds before the token's stated expiry to avoid races.
_TOKEN_REFRESH_MARGIN = 60


class NotiOneError(Exception):
    """Base error for the notiOne client."""


class NotiOneAuthError(NotiOneError):
    """Raised when credentials are rejected."""


class NotiOneApiError(NotiOneError):
    """Raised for transport or unexpected API errors."""


class NotiOneApi:
    """Logs in and fetches the device list, re-authenticating as needed."""

    def __init__(self, session: ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    @property
    def session(self) -> ClientSession:
        """Return the shared Home Assistant HTTP session."""
        return self._session

    async def login(self) -> None:
        """Authenticate and cache an access token.

        Raises NotiOneAuthError on bad credentials, NotiOneApiError otherwise.
        """
        payload = {
            "email": self._email,
            "password": self._password,
            "scope": SCOPE,
        }
        headers = {
            "Authorization": CLIENT_BASIC_AUTH,
            "Content-Type": "application/json",
        }
        try:
            async with self._session.post(
                LOGIN_URL, json=payload, headers=headers
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise NotiOneAuthError("notiOne rejected the credentials")
                resp.raise_for_status()
                data = await resp.json()
        except NotiOneAuthError:
            raise
        except ClientResponseError as err:
            raise NotiOneApiError(f"Login failed: HTTP {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise NotiOneApiError(f"Login transport error: {err}") from err

        token = data.get("accessToken")
        if not token:
            raise NotiOneApiError("Login response missing accessToken")
        # expiresIn is seconds; default to 3600 if absent.
        expires_in = int(data.get("expiresIn", 3600))
        self._access_token = token
        self._token_expiry = time.monotonic() + expires_in
        _LOGGER.debug("notiOne login OK, token valid for %ss", expires_in)

    async def _ensure_token(self) -> None:
        if (
            self._access_token is None
            or time.monotonic() >= self._token_expiry - _TOKEN_REFRESH_MARGIN
        ):
            await self.login()

    async def async_auth_headers(self) -> dict[str, str]:
        """Return current authentication headers for REST or WebSocket calls."""
        await self._ensure_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": API_ACCEPT,
            "User-Agent": USER_AGENT,
        }

    async def async_get_devices(self) -> list[dict]:
        """Return the raw deviceList, refreshing auth on expiry or 401."""
        await self._ensure_token()
        try:
            return await self._fetch_devices()
        except NotiOneAuthError:
            # Token rejected mid-flight — log in again once and retry.
            _LOGGER.debug("notiOne token rejected, re-authenticating")
            await self.login()
            return await self._fetch_devices()

    async def _fetch_devices(self) -> list[dict]:
        headers = await self.async_auth_headers()
        try:
            async with self._session.get(DEVICELIST_URL, headers=headers) as resp:
                if resp.status == 401:
                    raise NotiOneAuthError("Device list returned 401")
                resp.raise_for_status()
                data = await resp.json()
        except NotiOneAuthError:
            raise
        except ClientResponseError as err:
            raise NotiOneApiError(f"Device list failed: HTTP {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise NotiOneApiError(f"Device list transport error: {err}") from err

        devices = data.get("deviceList")
        if devices is None:
            raise NotiOneApiError("Device list response missing deviceList")
        return devices

    async def async_get_device_config(self, device_id: int) -> dict[str, Any]:
        """Read the full configuration model for a GPS device."""
        return await self._request_device_config("GET", device_id)

    async def async_set_device_config(
        self, device_id: int, config: dict[str, Any]
    ) -> None:
        """Write a full device configuration model."""
        await self._request_device_config("POST", device_id, config)

    async def _request_device_config(
        self, method: str, device_id: int, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self._ensure_token()
        try:
            return await self._fetch_device_config(method, device_id, payload)
        except NotiOneAuthError:
            await self.login()
            return await self._fetch_device_config(method, device_id, payload)

    async def _fetch_device_config(
        self, method: str, device_id: int, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        headers = await self.async_auth_headers()
        url = f"{DEVICECONFIG_URL}?deviceId={device_id}"
        try:
            async with self._session.request(
                method, url, headers=headers, json=payload
            ) as resp:
                if resp.status == 401:
                    raise NotiOneAuthError("Device config returned 401")
                resp.raise_for_status()
                body = await resp.text()
                if not body:
                    return {}
                data = json.loads(body)
        except NotiOneAuthError:
            raise
        except ClientResponseError as err:
            raise NotiOneApiError(
                f"Device config failed: HTTP {err.status}"
            ) from err
        except json.JSONDecodeError as err:
            raise NotiOneApiError("Device config response is not valid JSON") from err
        except (ClientError, TimeoutError) as err:
            raise NotiOneApiError(f"Device config transport error: {err}") from err
        if method == "GET" and not isinstance(data, dict):
            raise NotiOneApiError("Device config response is not an object")
        return data if isinstance(data, dict) else {}
