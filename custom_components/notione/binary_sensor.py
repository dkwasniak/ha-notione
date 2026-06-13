"""Binary sensor platform for notiOne — exposes motion state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NotiOneConfigEntry
from .const import DOMAIN
from .coordinator import NotiOneCoordinator, device_display_name, device_is_moving
from .device_tracker import _has_position, name_override


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotiOneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a motion binary sensor for each positioned device."""
    coordinator = entry.runtime_data
    override = name_override(entry)
    async_add_entities(
        NotiOneMovingSensor(coordinator, device_id, override)
        for device_id, device in coordinator.data.items()
        if _has_position(device)
    )


class NotiOneMovingSensor(CoordinatorEntity[NotiOneCoordinator], BinarySensorEntity):
    """On when the notiOne device reports motion."""

    _attr_has_entity_name = True
    _attr_translation_key = "moving"
    _attr_device_class = BinarySensorDeviceClass.MOVING

    def __init__(
        self,
        coordinator: NotiOneCoordinator,
        device_id: int,
        override: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"notione_{device_id}_moving"
        device = coordinator.data.get(device_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=device_display_name(device, device_id, override),
        )

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data

    @property
    def is_on(self) -> bool:
        return device_is_moving(self.coordinator.data.get(self._device_id, {}))
