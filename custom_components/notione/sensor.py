"""Sensor platform for notiOne — per-device telemetry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NotiOneConfigEntry
from .const import DOMAIN
from .coordinator import NotiOneCoordinator, device_display_name
from .device_tracker import _has_position, name_override


def _position(device: dict) -> dict:
    return device.get("lastPosition") or {}


def _last_seen(device: dict) -> datetime | None:
    gpstime = _position(device).get("gpstime")
    if not gpstime:
        return None
    return datetime.fromtimestamp(gpstime / 1000, tz=timezone.utc)


@dataclass(frozen=True, kw_only=True)
class NotiOneSensorDescription(SensorEntityDescription):
    """Describes a notiOne sensor and how to read its value from a device."""

    value_fn: Callable[[dict], Any]


SENSORS: tuple[NotiOneSensorDescription, ...] = (
    NotiOneSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("gpsDetails") or {}).get("battery"),
    ),
    NotiOneSensorDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _position(d).get("speed"),
    ),
    NotiOneSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _position(d).get("temperature"),
    ),
    NotiOneSensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _position(d).get("humidity"),
    ),
    NotiOneSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_seen,
    ),
    NotiOneSensorDescription(
        key="geocode_city",
        translation_key="geocode_city",
        value_fn=lambda d: _position(d).get("geocodeCity"),
    ),
    NotiOneSensorDescription(
        key="geocode_place",
        translation_key="geocode_place",
        value_fn=lambda d: _position(d).get("geocodePlace"),
    ),
    NotiOneSensorDescription(
        key="device_state",
        translation_key="device_state",
        value_fn=lambda d: d.get("deviceState"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotiOneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the telemetry sensors for each positioned device."""
    coordinator = entry.runtime_data
    override = name_override(entry)
    async_add_entities(
        NotiOneSensor(coordinator, device_id, description, override)
        for device_id, device in coordinator.data.items()
        if _has_position(device)
        for description in SENSORS
    )


class NotiOneSensor(CoordinatorEntity[NotiOneCoordinator], SensorEntity):
    """A single telemetry value read from a notiOne device."""

    _attr_has_entity_name = True
    entity_description: NotiOneSensorDescription

    def __init__(
        self,
        coordinator: NotiOneCoordinator,
        device_id: int,
        description: NotiOneSensorDescription,
        override: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device_id
        self._attr_unique_id = f"notione_{device_id}_{description.key}"
        device = coordinator.data.get(device_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=device_display_name(device, device_id, override),
        )

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data

    @property
    def native_value(self) -> Any:
        device = self.coordinator.data.get(self._device_id, {})
        return self.entity_description.value_fn(device)
