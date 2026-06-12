"""Data update coordinator for notiOne."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NotiOneApi, NotiOneApiError, NotiOneAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class NotiOneCoordinator(DataUpdateCoordinator[dict[int, dict]]):
    """Polls the notiOne device list and exposes it keyed by deviceId."""

    def __init__(
        self, hass: HomeAssistant, api: NotiOneApi, scan_interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict[int, dict]:
        try:
            devices = await self.api.async_get_devices()
        except NotiOneAuthError as err:
            # Surface as auth failure so HA can trigger reauth.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except NotiOneApiError as err:
            raise UpdateFailed(str(err)) from err

        return {dev["deviceId"]: dev for dev in devices if "deviceId" in dev}
