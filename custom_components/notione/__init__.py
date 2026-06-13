"""The notiOne integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, STATE_HOME, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event

from .api import NotiOneApi
from .const import (
    CONF_EMAIL,
    CONF_IDLE_INTERVAL,
    CONF_MOVING_GRACE,
    CONF_MOVING_INTERVAL,
    CONF_MOVING_TRIGGER,
    CONF_PASSWORD,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_MOVING_GRACE,
    DEFAULT_MOVING_INTERVAL,
    DOMAIN,
)
from .coordinator import NotiOneCoordinator

_CONNECTED_STATES = (STATE_ON, STATE_HOME)

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

NotiOneConfigEntry = ConfigEntry[NotiOneCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: NotiOneConfigEntry) -> bool:
    """Set up notiOne from a config entry."""
    session = async_get_clientsession(hass)
    api = NotiOneApi(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    idle_interval = entry.options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)
    moving_interval = entry.options.get(
        CONF_MOVING_INTERVAL, DEFAULT_MOVING_INTERVAL
    )
    grace = entry.options.get(CONF_MOVING_GRACE, DEFAULT_MOVING_GRACE)
    coordinator = NotiOneCoordinator(
        hass, api, idle_interval, moving_interval, grace
    )

    # Optional external "bike connected" trigger entity → forces fast polling.
    trigger_entity = entry.options.get(CONF_MOVING_TRIGGER)
    if trigger_entity:
        state = hass.states.get(trigger_entity)
        coordinator.set_connection(
            state is not None and state.state in _CONNECTED_STATES,
            request_refresh=False,
        )

        @callback
        def _trigger_changed(event: Event) -> None:
            new_state = event.data.get("new_state")
            coordinator.set_connection(
                new_state is not None and new_state.state in _CONNECTED_STATES
            )

        entry.async_on_unload(
            async_track_state_change_event(
                hass, trigger_entity, _trigger_changed
            )
        )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NotiOneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: NotiOneConfigEntry
) -> None:
    """Reload the entry when options (polling intervals) change."""
    await hass.config_entries.async_reload(entry.entry_id)
