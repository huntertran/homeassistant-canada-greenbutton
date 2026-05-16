"""Config flow for Canada GreenButton."""
from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEFAULT_TZ,
    CONF_PUSH_STATS,
    CONF_WATCH_DIR,
    DEFAULT_TZ,
    DOMAIN,
    IMPORT_DIR,
)

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_WATCH_DIR, default=defaults.get(CONF_WATCH_DIR, "")): str,
        vol.Optional(CONF_PUSH_STATS, default=defaults.get(CONF_PUSH_STATS, True)): bool,
        vol.Optional(CONF_DEFAULT_TZ, default=defaults.get(CONF_DEFAULT_TZ, DEFAULT_TZ)): str,
    })


class CanadaGreenButtonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            watch = user_input.get(CONF_WATCH_DIR, "").strip()
            if watch and not os.path.isdir(watch):
                errors[CONF_WATCH_DIR] = "invalid_dir"
            if not errors:
                # Ensure import dir exists
                import_path = self.hass.config.path(IMPORT_DIR)
                os.makedirs(import_path, exist_ok=True)
                return self.async_create_entry(
                    title="Canada GreenButton",
                    data={},
                    options=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> "OptionsFlow":
        return OptionsFlow(entry)


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            watch = user_input.get(CONF_WATCH_DIR, "").strip()
            if watch and not os.path.isdir(watch):
                errors[CONF_WATCH_DIR] = "invalid_dir"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(dict(self.entry.options) if user_input is None else user_input),
            errors=errors,
        )
