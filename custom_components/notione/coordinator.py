"""Data update coordinator for notiOne."""

from __future__ import annotations

import asyncio
import logging
import time
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
        grace_seconds: int = 0,
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
        self._grace_seconds = grace_seconds
        self.moving = False
        # External "bike connected" trigger and its post-disconnect bridge window.
        self._connected = False
        self._grace_until = 0.0

    def set_connection(self, active: bool, request_refresh: bool = True) -> None:
        """Feed the external connection-trigger state into the cadence logic.

        On connect: force the fast interval and (optionally) fetch immediately.
        On disconnect: open a grace window so polling stays fast while the
        device's LTE modem wakes up, until API motion takes over.
        """
        if active == self._connected:
            return
        self._connected = active
        if active:
            self.update_interval = timedelta(seconds=self._moving_interval)
            if request_refresh:
                self.hass.async_create_task(self.async_request_refresh())
        else:
            self._grace_until = time.monotonic() + self._grace_seconds

    async def _async_update_data(self) -> dict[int, dict]:
        try:
            devices = await self.api.async_get_devices()
        except NotiOneAuthError as err:
            # Surface as auth failure so HA can trigger reauth.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except NotiOneApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {dev["deviceId"]: dev for dev in devices if "deviceId" in dev}

        # Fetch latest history sample in parallel for comparison sensor.
        positioned = [did for did, dev in data.items() if dev.get("lastPosition")]
        if positioned:
            results = await asyncio.gather(
                *(self.api.async_get_latest_sample_gpstime(did) for did in positioned),
                return_exceptions=True,
            )
            for device_id, result in zip(positioned, results):
                if isinstance(result, int):
                    data[device_id]["_history_gpstime"] = result

        # Adapt the polling cadence. Fast when the API reports motion, while the
        # connection trigger is on, or within the post-disconnect grace window.
        # DataUpdateCoordinator reads self.update_interval when scheduling the
        # next refresh, so mutating it here takes effect from the next cycle on.
        api_moving = any(device_is_moving(dev) for dev in data.values())
        bridge = time.monotonic() < self._grace_until
        fast = api_moving or self._connected or bridge
        if fast != self.moving:
            _LOGGER.debug(
                "notiOne fast-poll %s -> every %ss (api_moving=%s connected=%s bridge=%s)",
                "on" if fast else "off",
                self._moving_interval if fast else self._idle_interval,
                api_moving,
                self._connected,
                bridge,
            )
        self.moving = fast
        self.update_interval = timedelta(
            seconds=self._moving_interval if fast else self._idle_interval
        )

        return data
