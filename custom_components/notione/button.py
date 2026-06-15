"""Buttons for notiOne devices."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NotiOneConfigEntry
from .device_tracker import name_override
from .entity import NotiOneDeviceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotiOneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    override = name_override(entry)
    async_add_entities(
        NotiOneRefreshConfigButton(coordinator, device_id, override)
        for device_id, device in coordinator.data.items()
        if (device.get("gpsDetails") or {}).get("imei") is not None
    )


class NotiOneRefreshConfigButton(NotiOneDeviceEntity, ButtonEntity):
    _attr_translation_key = "refresh_config"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id: int, override: str | None) -> None:
        super().__init__(coordinator, device_id, "refresh_config", override)

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_device_config(self._device_id)
