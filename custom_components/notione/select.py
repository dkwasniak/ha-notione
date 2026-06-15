"""Interval selectors for notiOne device configuration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NotiOneConfigEntry
from .const import STATIONARY_INTERVALS
from .device_tracker import name_override
from .entity import NotiOneConfigEntity


def _format_interval(value: int) -> str:
    if value % 3600 == 0:
        return f"{value // 3600} h"
    if value % 60 == 0:
        return f"{value // 60} min"
    return f"{value} s"


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
            NotiOneIntervalSelect(
                coordinator,
                device_id,
                "move_interval",
                "movePositionInterval",
                False,
                override,
            ),
            NotiOneIntervalSelect(
                coordinator,
                device_id,
                "stationary_interval",
                "stationaryPositionInterval",
                True,
                override,
            ),
            NotiOneIntervalSelect(
                coordinator,
                device_id,
                "battery_alarm_interval",
                "batterySavingAlarmMoveInterval",
                False,
                override,
            ),
        )
    )


class NotiOneIntervalSelect(NotiOneConfigEntity, SelectEntity):
    def __init__(
        self,
        coordinator,
        device_id: int,
        key: str,
        field: str,
        stationary: bool,
        override: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, key, override)
        self._attr_translation_key = key
        self._field = field
        self._stationary = stationary

    @property
    def _values(self) -> dict[str, int]:
        if self._stationary:
            return STATIONARY_INTERVALS
        values = self.device_config.get("allowedMoveIntervals") or []
        return {
            _format_interval(value): value
            for value in values
            if isinstance(value, int) and value > 0
        }

    @property
    def options(self) -> list[str]:
        return list(self._values)

    @property
    def current_option(self) -> str | None:
        current = self.device_config.get(self._field)
        return next(
            (label for label, value in self._values.items() if value == current), None
        )

    async def async_select_option(self, option: str) -> None:
        if option not in self._values:
            raise ValueError(f"Unknown interval option: {option}")
        await self.coordinator.async_update_device_config(
            self._device_id, self._field, self._values[option]
        )
