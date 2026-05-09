"""Config flow for Tasmota REST."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    CONF_VIRTUAL_SWITCH_ENABLED,
    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
    CONF_VIRTUAL_SWITCH_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_VIRTUAL_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """Connection failure."""


async def _validate_host(hass, user_input: dict[str, Any]) -> dict[str, Any]:
    session = async_get_clientsession(
        hass, verify_ssl=bool(user_input.get(CONF_VERIFY_SSL, False))
    )
    scheme = "https" if user_input.get(CONF_USE_HTTPS) else "http"
    host = user_input[CONF_HOST]
    url = f"{scheme}://{host}/cm"
    params: dict[str, str] = {"cmnd": "Status 0"}
    if user_input.get(CONF_USERNAME):
        params["user"] = user_input[CONF_USERNAME]
    if user_input.get(CONF_PASSWORD):
        params["password"] = user_input[CONF_PASSWORD]

    try:
        async with async_timeout.timeout(DEFAULT_TIMEOUT):
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError) as err:
        raise CannotConnect(str(err)) from err
    except ValueError as err:
        raise CannotConnect(f"Invalid JSON from device: {err}") from err

    status = data.get("Status") or {}
    net = data.get("StatusNET") or {}
    friendly = status.get("FriendlyName")
    if isinstance(friendly, list) and friendly:
        title = str(friendly[0])
    elif isinstance(friendly, str):
        title = friendly
    else:
        title = status.get("DeviceName") or host

    return {"title": title, "unique_id": net.get("Mac") or host}


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=2, max=300, step=1, mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Optional(CONF_USE_HTTPS, default=defaults.get(CONF_USE_HTTPS, False)): bool,
            vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, False)): bool,
            vol.Optional(
                CONF_VIRTUAL_SWITCH_ENABLED,
                default=defaults.get(CONF_VIRTUAL_SWITCH_ENABLED, False),
            ): bool,
            vol.Optional(
                CONF_VIRTUAL_SWITCH_THRESHOLD,
                default=defaults.get(CONF_VIRTUAL_SWITCH_THRESHOLD, DEFAULT_VIRTUAL_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=4000, step=1, mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="W",
                )
            ),
            vol.Optional(
                CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
                default=defaults.get(CONF_VIRTUAL_SWITCH_PRESS_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="button")
            ),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Strip empty optional strings; coerce numeric fields."""
    cleaned = {}
    for key, value in user_input.items():
        if isinstance(value, str) and value.strip() == "":
            continue
        cleaned[key] = value
    if CONF_SCAN_INTERVAL in cleaned:
        cleaned[CONF_SCAN_INTERVAL] = int(float(cleaned[CONF_SCAN_INTERVAL]))
    if CONF_VIRTUAL_SWITCH_THRESHOLD in cleaned:
        cleaned[CONF_VIRTUAL_SWITCH_THRESHOLD] = float(cleaned[CONF_VIRTUAL_SWITCH_THRESHOLD])
    return cleaned


class TasmotaRestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tasmota REST."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned = _clean(user_input)
            try:
                info = await _validate_host(self.hass, cleaned)
            except CannotConnect as err:
                _LOGGER.warning("Tasmota REST connection failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Tasmota host")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured(updates=cleaned)
                title = cleaned.get(CONF_NAME) or info["title"]
                return self.async_create_entry(title=title, data=cleaned)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    async def async_step_import(self, user_input: dict[str, Any]) -> FlowResult:
        """Import device from YAML."""
        cleaned = _clean(user_input)
        try:
            info = await _validate_host(self.hass, cleaned)
        except CannotConnect as err:
            _LOGGER.error(
                "Tasmota REST YAML import failed for %s: %s",
                cleaned.get(CONF_HOST), err,
            )
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(info["unique_id"])
        self._abort_if_unique_id_configured(updates=cleaned)
        title = cleaned.get(CONF_NAME) or info["title"]
        return self.async_create_entry(title=title, data=cleaned)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "TasmotaRestOptionsFlow":
        return TasmotaRestOptionsFlow(config_entry)


class TasmotaRestOptionsFlow(config_entries.OptionsFlow):
    """Options flow for adjusting per-device settings without re-adding."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=_clean(user_input))

        merged = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=2, max=300, step=1, mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_ENABLED,
                    default=merged.get(CONF_VIRTUAL_SWITCH_ENABLED, False),
                ): bool,
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_THRESHOLD,
                    default=merged.get(CONF_VIRTUAL_SWITCH_THRESHOLD, DEFAULT_VIRTUAL_THRESHOLD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=4000, step=1, mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
                    default=merged.get(CONF_VIRTUAL_SWITCH_PRESS_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="button")
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
