"""Numeric alarm thresholds for notiOne devices."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import PERCENTAGE, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NotiOneConfigEntry
from .device_tracker import name_override
from .entity import NotiOneConfigEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NotiOneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    override = name_override(entry)
    async_add_entities(
        entity
        for device_id, device in coordinator.data.items()
        if (device.get("gpsDetails") or {}).get("imei") is not None
        for entity in (
            NotiOneConfigNumber(
                coordinator,
                device_id,
                "speed_alarm_threshold",
                "speedExceedAlarmThreshold",
                0,
                300,
                UnitOfSpeed.KILOMETERS_PER_HOUR,
                override,
            ),
            NotiOneConfigNumber(
                coordinator,
                device_id,
                "battery_alarm_threshold",
                "batterySavingAlarmThreshold",
                0,
                100,
                PERCENTAGE,
                override,
            ),
        )
    )


class NotiOneConfigNumber(NotiOneConfigEntity, NumberEntity):
    _attr_native_step = 1

    def __init__(
        self,
        coordinator,
        device_id: int,
        key: str,
        field: str,
        minimum: int,
        maximum: int,
        unit: str,
        override: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, key, override)
        self._attr_translation_key = key
        self._field = field
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        value = self.device_config.get(self._field)
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_device_config(
            self._device_id, self._field, int(value)
        )
