"""Config and options flow for notiOne."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NotiOneApi, NotiOneApiError, NotiOneAuthError
from .const import (
    CONF_EMAIL,
    CONF_IDLE_INTERVAL,
    CONF_MOVING_INTERVAL,
    CONF_PASSWORD,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_MOVING_INTERVAL,
    DOMAIN,
    MAX_INTERVAL,
    MIN_INTERVAL,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_NAME, default=""): str,
    }
)


class NotiOneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial credential setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = NotiOneApi(session, email, user_input[CONF_PASSWORD])
            try:
                await api.login()
            except NotiOneAuthError:
                errors["base"] = "invalid_auth"
            except NotiOneApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=email, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NotiOneOptionsFlow()


class NotiOneOptionsFlow(OptionsFlow):
    """Allow tuning the idle and moving polling intervals."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        current_name = options.get(
            CONF_NAME, self.config_entry.data.get(CONF_NAME, "")
        )
        interval = vol.All(
            vol.Coerce(int), vol.Range(min=MIN_INTERVAL, max=MAX_INTERVAL)
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current_name): str,
                vol.Required(
                    CONF_IDLE_INTERVAL,
                    default=options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL),
                ): interval,
                vol.Required(
                    CONF_MOVING_INTERVAL,
                    default=options.get(
                        CONF_MOVING_INTERVAL, DEFAULT_MOVING_INTERVAL
                    ),
                ): interval,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
