"""Device tracker platform for notiOne GPS locators."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NotiOneConfigEntry
from .const import DOMAIN
from .coordinator import NotiOneCoordinator, device_display_name


def _has_position(device: dict) -> bool:
    """True if the device exposes a usable GPS fix (skips phones/beacons)."""
    pos = device.get("lastPosition")
    return bool(pos and pos.get("latitude") is not None)


def name_override(entry: NotiOneConfigEntry) -> str | None:
    """User-supplied device name, options taking precedence over setup data."""
    return entry.options.get(CONF_NAME) or entry.data.get(CONF_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotiOneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a tracker entity for each notiOne device that reports a position."""
    coordinator = entry.runtime_data
    override = name_override(entry)
    async_add_entities(
        NotiOneTracker(coordinator, device_id, override)
        for device_id, device in coordinator.data.items()
        if _has_position(device)
    )


class NotiOneTracker(CoordinatorEntity[NotiOneCoordinator], TrackerEntity):
    """Represents one notiOne GPS device on the map."""

    _attr_has_entity_name = True
    _attr_name = None  # use the device name as the entity name
    _attr_icon = "mdi:bike"

    def __init__(
        self,
        coordinator: NotiOneCoordinator,
        device_id: int,
        override: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"notione_{device_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=device_display_name(self._device, device_id, override),
            manufacturer="notiOne",
            model=self._device.get("deviceType"),
        )

    @property
    def _device(self) -> dict:
        return self.coordinator.data.get(self._device_id, {})

    @property
    def _position(self) -> dict:
        return self._device.get("lastPosition") or {}

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._position.get("latitude")

    @property
    def longitude(self) -> float | None:
        return self._position.get("longitude")

    @property
    def location_accuracy(self) -> int:
        return int(self._position.get("accuracy") or 0)

    @property
    def battery_level(self) -> int | None:
        gps = self._device.get("gpsDetails") or {}
        return gps.get("battery")

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
