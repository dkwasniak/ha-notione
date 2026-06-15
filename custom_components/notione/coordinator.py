"""Data, LIVE-session and device-configuration coordinator for notiOne."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

from aiohttp import ClientError, ClientWebSocketResponse, WSMsgType
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NotiOneApi, NotiOneApiError, NotiOneAuthError
from .const import (
    CONF_GARAGE_ENTITY,
    CONF_ZONE_ENTITY,
    DOMAIN,
    LIVE_WS_URL,
)
from .live_protocol import (
    build_enable_request,
    parse_server_message,
    reason_for_close_code,
)
from .logic import (
    build_device_config_payload,
    coordinates_in_zone,
    evaluate_live_automation,
)

_LOGGER = logging.getLogger(__name__)

_WRITABLE_CONFIG_FIELDS = {
    "movePositionInterval",
    "stationaryPositionInterval",
    "theftAlarmStatus",
    "etollEnabled",
    "allowCollectGpsData",
    "theftAlarmMode",
    "theftAlarmWholeDayNotification",
    "theftAlarmBeginTime",
    "theftAlarmEndTime",
    "allowDisableDevice",
    "theftAlarmSoundEnabled",
    "speedExceedAlarmEnabled",
    "speedExceedAlarmThreshold",
    "batterySavingAlarmEnabled",
    "batterySavingAlarmThreshold",
    "batterySavingAlarmMoveInterval",
}


def device_display_name(device: dict, device_id: int, override: str | None) -> str:
    """Resolve the device name: user override, API name, or fallback."""
    return (override or "").strip() or device.get("name") or f"notiOne {device_id}"


def device_is_offline(device: dict) -> bool:
    """Return whether notiOne reports stale/offline device data."""
    return device.get("deviceState") == "OFFLINE"


def device_is_moving(device: dict) -> bool:
    """Return whether a device currently reports motion."""
    if device_is_offline(device):
        return False
    pos = device.get("lastPosition") or {}
    accel = pos.get("accelerometerStatusEnum")
    if accel is not None:
        return accel == "MOVE"
    return bool(pos.get("speed"))


def point_in_zone(position: dict, zone_state: Any) -> bool | None:
    """Return zone membership, or None when coordinates are unavailable."""
    if zone_state is None or zone_state.state in ("unknown", "unavailable"):
        return None
    try:
        latitude = position["latitude"]
        longitude = position["longitude"]
        zone_latitude = zone_state.attributes["latitude"]
        zone_longitude = zone_state.attributes["longitude"]
        radius = zone_state.attributes["radius"]
    except (KeyError, TypeError):
        return None
    return coordinates_in_zone(
        latitude, longitude, zone_latitude, zone_longitude, radius
    )


@dataclass
class LiveState:
    """Observable state for one LIVE session."""

    source: str | None = None
    connecting: bool = False
    active: bool = False
    max_session_time: int | None = None
    close_code: int | None = None
    reason: str | None = None
    task: asyncio.Task[None] | None = None
    websocket: ClientWebSocketResponse | None = None

    @property
    def is_on(self) -> bool:
        return self.connecting or self.active


class NotiOneCoordinator(DataUpdateCoordinator[dict[int, dict]]):
    """Coordinate REST polling, LIVE sockets and per-device settings."""

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
        self._connected = False
        self._grace_until = 0.0
        self.live_states: dict[int, LiveState] = {}
        self.device_configs: dict[int, dict[str, Any]] = {}
        self._config_locks: dict[int, asyncio.Lock] = {}
        self._automations: dict[int, dict[str, str]] = {}
        self._zone_armed: dict[int, bool] = {}
        self._automation_unsub: list[Callable[[], None]] = []
        self._evaluation_lock = asyncio.Lock()
        self._shutting_down = False

    def set_connection(self, active: bool, request_refresh: bool = True) -> None:
        """Feed the legacy external connection state into polling cadence."""
        if active == self._connected:
            return
        self._connected = active
        if active:
            self._set_poll_interval(self._moving_interval)
            if request_refresh and not self.live_active:
                self.hass.async_create_task(self.async_request_refresh())
        else:
            self._grace_until = time.monotonic() + self._grace_seconds

    @property
    def live_active(self) -> bool:
        """Return whether any LIVE session is connecting or active."""
        return any(state.is_on for state in self.live_states.values())

    def _set_poll_interval(self, seconds: int | None) -> None:
        self.update_interval = None if seconds is None else timedelta(seconds=seconds)

    async def _async_update_data(self) -> dict[int, dict]:
        if self.live_active:
            return self.data
        try:
            devices = await self.api.async_get_devices()
        except NotiOneAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except NotiOneApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {dev["deviceId"]: dev for dev in devices if "deviceId" in dev}
        api_moving = any(device_is_moving(dev) for dev in data.values())
        bridge = time.monotonic() < self._grace_until
        fast = api_moving or self._connected or bridge
        self.moving = fast
        self._set_poll_interval(
            self._moving_interval if fast else self._idle_interval
        )
        return data

    async def async_load_device_configs(self) -> None:
        """Fetch configuration for every GPS device without failing setup."""
        device_ids = [
            device_id
            for device_id, device in self.data.items()
            if (device.get("gpsDetails") or {}).get("imei") is not None
        ]
        results = await asyncio.gather(
            *(self.api.async_get_device_config(device_id) for device_id in device_ids),
            return_exceptions=True,
        )
        for device_id, result in zip(device_ids, results):
            if isinstance(result, dict):
                self.device_configs[device_id] = result
            else:
                _LOGGER.warning(
                    "Could not load config for device %s: %s", device_id, result
                )

    async def async_refresh_device_config(self, device_id: int) -> None:
        """Refresh one device configuration and notify entities."""
        lock = self._config_locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            self.device_configs[device_id] = await self.api.async_get_device_config(
                device_id
            )
        self.async_update_listeners()

    async def async_update_device_config(
        self, device_id: int, field: str, value: Any
    ) -> None:
        """Perform serialized GET, mutate, full POST, GET for one field."""
        lock = self._config_locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            current = await self.api.async_get_device_config(device_id)
            payload = build_device_config_payload(
                current, field, value, _WRITABLE_CONFIG_FIELDS
            )
            await self.api.async_set_device_config(device_id, payload)
            self.device_configs[device_id] = await self.api.async_get_device_config(
                device_id
            )
        self.async_update_listeners()

    def configure_automations(self, automations: dict[str, Any]) -> None:
        """Install state listeners for configured zones and garage sensors."""
        self._automations = {
            int(device_id): config
            for device_id, config in automations.items()
            if str(device_id).isdigit() and isinstance(config, dict)
        }
        for device_id in self.data:
            self._zone_armed[device_id] = True
        entities = {
            entity_id
            for config in self._automations.values()
            for key in (CONF_ZONE_ENTITY, CONF_GARAGE_ENTITY)
            if (entity_id := config.get(key))
        }
        if entities:
            self._automation_unsub.append(
                async_track_state_change_event(
                    self.hass, list(entities), self._state_changed
                )
            )
        self._automation_unsub.append(self.async_add_listener(self._data_changed))
        self.hass.async_create_task(self.async_evaluate_automations())

    @callback
    def _state_changed(self, event: Event) -> None:
        self.hass.async_create_task(self.async_evaluate_automations())

    @callback
    def _data_changed(self) -> None:
        self.hass.async_create_task(self.async_evaluate_automations())

    async def async_evaluate_automations(self) -> None:
        """Apply offline, garage and zone rules to every GPS device."""
        if self._shutting_down:
            return
        async with self._evaluation_lock:
            for device_id, device in self.data.items():
                state = self.live_states.setdefault(device_id, LiveState())
                config = self._automations.get(device_id, {})
                garage_entity = config.get(CONF_GARAGE_ENTITY)
                garage_on = bool(
                    garage_entity
                    and (garage := self.hass.states.get(garage_entity)) is not None
                    and garage.state == STATE_ON
                )
                zone_entity = config.get(CONF_ZONE_ENTITY)
                inside = point_in_zone(
                    device.get("lastPosition") or {},
                    self.hass.states.get(zone_entity) if zone_entity else None,
                )
                decision = evaluate_live_automation(
                    live_on=state.is_on,
                    source=state.source,
                    offline=device_is_offline(device),
                    garage_on=garage_on,
                    inside=inside,
                    armed=self._zone_armed.get(device_id, True),
                )
                self._zone_armed[device_id] = decision.armed
                if decision.action == "start":
                    await self.async_start_live(device_id, "zone")
                elif decision.action == "stop" and decision.reason:
                    await self.async_stop_live(device_id, decision.reason)

    async def async_start_live(self, device_id: int, source: str = "manual") -> None:
        """Start one LIVE WebSocket session."""
        device = self.data.get(device_id, {})
        imei = (device.get("gpsDetails") or {}).get("imei")
        state = self.live_states.setdefault(device_id, LiveState())
        if self._shutting_down or state.is_on or not isinstance(imei, int):
            return
        self._zone_armed[device_id] = False
        state.source = source
        state.connecting = True
        state.active = False
        state.max_session_time = None
        state.close_code = None
        state.reason = None
        self._set_poll_interval(None)
        state.task = self.hass.async_create_task(
            self._async_live_loop(device_id, imei)
        )
        self.async_update_listeners()

    async def _async_live_loop(self, device_id: int, imei: int) -> None:
        state = self.live_states[device_id]
        close_code: int | None = None
        close_reason: str | None = None
        try:
            headers = await self.api.async_auth_headers()
            async with self.api.session.ws_connect(
                LIVE_WS_URL, headers=headers, heartbeat=30
            ) as websocket:
                state.websocket = websocket
                await websocket.send_bytes(build_enable_request(imei))
                async for message in websocket:
                    if message.type == WSMsgType.BINARY:
                        kind, payload = parse_server_message(message.data)
                        if kind == "config":
                            state.connecting = False
                            state.active = True
                            state.max_session_time = payload["max_session_time"]
                            self.async_update_listeners()
                        elif kind == "sample":
                            self._apply_live_sample(device_id, payload)
                    elif message.type == WSMsgType.ERROR:
                        raise websocket.exception() or ClientError("LIVE socket error")
                    elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED):
                        break
                close_code = websocket.close_code
                close_reason = reason_for_close_code(close_code)
        except asyncio.CancelledError:
            close_code = state.close_code or 3000
            close_reason = state.reason or "integration_unload"
        except (ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("LIVE session failed for device %s: %s", device_id, err)
            close_reason = str(err)
        finally:
            state.websocket = None
            state.task = None
            state.connecting = False
            state.active = False
            state.close_code = state.close_code or close_code
            state.reason = (
                state.reason or close_reason or reason_for_close_code(close_code)
            )
            self.async_update_listeners()
            if not self.live_active and not self._shutting_down:
                self._restore_polling_and_refresh()

    def _apply_live_sample(self, device_id: int, sample: dict[str, Any]) -> None:
        data = dict(self.data)
        device = dict(data.get(device_id, {}))
        position = dict(device.get("lastPosition") or {})
        position.update(sample)
        position.pop("imei", None)
        device["lastPosition"] = position
        device["deviceState"] = "ONLINE"
        data[device_id] = device
        self.async_set_updated_data(data)

    async def async_stop_live(self, device_id: int, reason: str = "manual") -> None:
        """Stop LIVE with the official client close code."""
        state = self.live_states.setdefault(device_id, LiveState())
        if not state.is_on:
            return
        if reason in ("manual", "offline", "garage_connected"):
            self._zone_armed[device_id] = False
        state.close_code = 3000
        state.reason = reason
        websocket = state.websocket
        task = state.task
        if websocket is not None and not websocket.closed:
            await websocket.close(code=3000, message=reason.encode("utf-8"))
        elif task is not None:
            task.cancel()
        if task is not None and task is not asyncio.current_task():
            try:
                await task
            except asyncio.CancelledError:
                pass
        if state.task is task:
            state.websocket = None
            state.task = None
            state.connecting = False
            state.active = False
            self.async_update_listeners()
            if not self.live_active and not self._shutting_down:
                self._restore_polling_and_refresh()

    def _restore_polling_and_refresh(self) -> None:
        seconds = self._moving_interval if self.moving else self._idle_interval
        self._set_poll_interval(seconds)
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        """Close sockets, listeners and tasks during integration unload."""
        self._shutting_down = True
        for unsubscribe in self._automation_unsub:
            unsubscribe()
        self._automation_unsub.clear()
        await asyncio.gather(
            *(
                self.async_stop_live(device_id, "integration_unload")
                for device_id, state in self.live_states.items()
                if state.is_on
            ),
            return_exceptions=True,
        )
        tasks = [state.task for state in self.live_states.values() if state.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
