"""Thin async client for the unofficial notiOne API."""

from __future__ import annotations

import logging
import time

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    CLIENT_BASIC_AUTH,
    DEVICELIST_URL,
    LOGIN_URL,
    SCOPE,
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
        headers = {"Authorization": f"Bearer {self._access_token}"}
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
