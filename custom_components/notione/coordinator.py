"""Data update coordinator for notiOne."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NotiOneApi, NotiOneApiError, NotiOneAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def device_display_name(device: dict, device_id: int, override: str | None) -> str:
    """Resolve the device name: user override, else API name, else a fallback."""
    return (override or "").strip() or device.get("name") or f"notiOne {device_id}"


def device_is_offline(device: dict) -> bool:
    """True when notiOne reports the device as offline (data is stale)."""
    return device.get("deviceState") == "OFFLINE"


def device_is_moving(device: dict) -> bool:
    """Return True if the device currently reports motion.

    An offline device is never moving — its lastPosition holds the last known
    (stale) values. Otherwise prefer the accelerometer status (notiOne reports
    "MOVE" when in motion) and fall back to a non-zero GPS speed.
    """
    if device_is_offline(device):
        return False
    pos = device.get("lastPosition") or {}
    accel = pos.get("accelerometerStatusEnum")
    if accel is not None:
        return accel == "MOVE"
    speed = pos.get("speed")
    return bool(speed and speed > 0)


class NotiOneCoordinator(DataUpdateCoordinator[dict[int, dict]]):
    """Polls the notiOne device list, speeding up while a device is moving."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: NotiOneApi,
        idle_interval: int,
        moving_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=idle_interval),
        )
        self.api = api
        self._idle_interval = idle_interval
        self._moving_interval = moving_interval
        self.moving = False

    async def _async_update_data(self) -> dict[int, dict]:
        try:
            devices = await self.api.async_get_devices()
        except NotiOneAuthError as err:
            # Surface as auth failure so HA can trigger reauth.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except NotiOneApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {dev["deviceId"]: dev for dev in devices if "deviceId" in dev}

        # Adapt the polling cadence to motion. DataUpdateCoordinator reads
        # self.update_interval when scheduling the next refresh, so mutating it
        # here takes effect from the next cycle on.
        moving = any(device_is_moving(dev) for dev in data.values())
        if moving != self.moving:
            _LOGGER.debug(
                "notiOne motion %s -> polling every %ss",
                "started" if moving else "stopped",
                self._moving_interval if moving else self._idle_interval,
            )
        self.moving = moving
        self.update_interval = timedelta(
            seconds=self._moving_interval if moving else self._idle_interval
        )

        return data
