"""Shared entity helpers for notiOne device entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NotiOneCoordinator, device_display_name


class NotiOneDeviceEntity(CoordinatorEntity[NotiOneCoordinator]):
    """Base for entities attached to one notiOne GPS device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NotiOneCoordinator,
        device_id: int,
        key: str,
        override: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"notione_{device_id}_{key}"
        device = coordinator.data.get(device_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=device_display_name(device, device_id, override),
        )

    @property
    def device_config(self) -> dict:
        """Return the latest server configuration for this device."""
        return self.coordinator.device_configs.get(self._device_id, {})

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.data


class NotiOneConfigEntity(NotiOneDeviceEntity):
    """Base for entities backed by deviceconfig."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return super().available and self._device_id in self.coordinator.device_configs
