"""Config flow for Tasmota REST."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import dhcp, zeroconf
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
    CONF_AP_AUTO_PROVISION,
    CONF_AP_IP,
    CONF_AP_SSID_PATTERN,
    CONF_AUTO_ADD_DISCOVERED,
    CONF_DEFAULT_PASSWORD,
    CONF_DEFAULT_USERNAME,
    CONF_HOSTNAME_TEMPLATE,
    CONF_SCAN_INTERVAL_MIN,
    CONF_SCAN_SUBNETS,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    CONF_VIRTUAL_SWITCH_ENABLED,
    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
    CONF_VIRTUAL_SWITCH_THRESHOLD,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_PASSWORD2,
    CONF_WIFI_SCAN_ENABLED,
    CONF_WIFI_SSID,
    CONF_WIFI_SSID2,
    DEFAULT_AP_IP,
    DEFAULT_AP_SSID_PATTERN,
    DEFAULT_PROBE_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_TIMEOUT,
    DEFAULT_VIRTUAL_THRESHOLD,
    DOMAIN,
    ENTRY_TYPE,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
    HUB_UNIQUE_ID,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    pass


def _format_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    cleaned = mac.replace(":", "").replace("-", "").upper()
    if len(cleaned) != 12:
        return mac.upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


async def _validate_host(hass, user_input: dict[str, Any]) -> dict[str, Any]:
    session = async_get_clientsession(hass, verify_ssl=bool(user_input.get(CONF_VERIFY_SSL, False)))
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
        raise CannotConnect(f"Invalid JSON: {err}") from err

    status = data.get("Status") or {}
    net = data.get("StatusNET") or {}
    friendly = status.get("FriendlyName")
    if isinstance(friendly, list) and friendly:
        title = str(friendly[0])
    elif isinstance(friendly, str):
        title = friendly
    else:
        title = status.get("DeviceName") or host

    return {"title": title, "unique_id": _format_mac(net.get("Mac")) or host}


def _device_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=2, max=300, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s"
                )
            ),
            vol.Optional(CONF_USE_HTTPS, default=defaults.get(CONF_USE_HTTPS, False)): bool,
            vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, False)): bool,
            vol.Optional(
                CONF_VIRTUAL_SWITCH_ENABLED, default=defaults.get(CONF_VIRTUAL_SWITCH_ENABLED, False)
            ): bool,
            vol.Optional(
                CONF_VIRTUAL_SWITCH_THRESHOLD,
                default=defaults.get(CONF_VIRTUAL_SWITCH_THRESHOLD, DEFAULT_VIRTUAL_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=4000, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="W"
                )
            ),
            vol.Optional(
                CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
                default=defaults.get(CONF_VIRTUAL_SWITCH_PRESS_ENTITY, ""),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="button")),
        }
    )


def _hub_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    subnets = defaults.get(CONF_SCAN_SUBNETS, [])
    if isinstance(subnets, list):
        subnets_default = ", ".join(subnets)
    else:
        subnets_default = subnets or ""
    return vol.Schema(
        {
            vol.Required(CONF_WIFI_SSID, default=defaults.get(CONF_WIFI_SSID, "")): str,
            vol.Optional(CONF_WIFI_PASSWORD, default=defaults.get(CONF_WIFI_PASSWORD, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_WIFI_SSID2, default=defaults.get(CONF_WIFI_SSID2, "")): str,
            vol.Optional(CONF_WIFI_PASSWORD2, default=defaults.get(CONF_WIFI_PASSWORD2, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_DEFAULT_USERNAME, default=defaults.get(CONF_DEFAULT_USERNAME, "")): str,
            vol.Optional(CONF_DEFAULT_PASSWORD, default=defaults.get(CONF_DEFAULT_PASSWORD, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_SCAN_SUBNETS, default=subnets_default): str,
            vol.Optional(
                CONF_SCAN_INTERVAL_MIN, default=defaults.get(CONF_SCAN_INTERVAL_MIN, DEFAULT_SCAN_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=240, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="min"
                )
            ),
            vol.Optional(CONF_AUTO_ADD_DISCOVERED, default=defaults.get(CONF_AUTO_ADD_DISCOVERED, False)): bool,
            vol.Optional(CONF_AP_AUTO_PROVISION, default=defaults.get(CONF_AP_AUTO_PROVISION, True)): bool,
            vol.Optional(CONF_AP_IP, default=defaults.get(CONF_AP_IP, DEFAULT_AP_IP)): str,
            vol.Optional(
                CONF_AP_SSID_PATTERN, default=defaults.get(CONF_AP_SSID_PATTERN, DEFAULT_AP_SSID_PATTERN)
            ): str,
            vol.Optional(CONF_WIFI_SCAN_ENABLED, default=defaults.get(CONF_WIFI_SCAN_ENABLED, True)): bool,
            vol.Optional(CONF_HOSTNAME_TEMPLATE, default=defaults.get(CONF_HOSTNAME_TEMPLATE, "")): str,
        }
    )


def _clean_device(user_input: dict[str, Any]) -> dict[str, Any]:
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


def _clean_hub(user_input: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in user_input.items():
        if key == CONF_SCAN_SUBNETS:
            if isinstance(value, str):
                parts = [p.strip() for p in value.split(",") if p.strip()]
                if parts:
                    cleaned[key] = parts
            elif value:
                cleaned[key] = value
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        cleaned[key] = value
    if CONF_SCAN_INTERVAL_MIN in cleaned:
        cleaned[CONF_SCAN_INTERVAL_MIN] = int(float(cleaned[CONF_SCAN_INTERVAL_MIN]))
    return cleaned


@callback
def _hub_already_configured(hass) -> bool:
    return any(
        e.data.get(ENTRY_TYPE) == ENTRY_TYPE_HUB
        for e in hass.config_entries.async_entries(DOMAIN)
    )


class TasmotaRestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Tasmota REST."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["device", "hub"] if not _hub_already_configured(self.hass) else ["device"],
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned = _clean_device(user_input)
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
                cleaned[ENTRY_TYPE] = ENTRY_TYPE_DEVICE
                title = cleaned.get(CONF_NAME) or info["title"]
                return self.async_create_entry(title=title, data=cleaned)

        return self.async_show_form(
            step_id="device", data_schema=_device_schema(user_input), errors=errors
        )

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if _hub_already_configured(self.hass):
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned = _clean_hub(user_input)
            await self.async_set_unique_id(HUB_UNIQUE_ID)
            self._abort_if_unique_id_configured()
            cleaned[ENTRY_TYPE] = ENTRY_TYPE_HUB
            return self.async_create_entry(
                title="Tasmota REST – auto-discovery & provisioning",
                data=cleaned,
            )

        return self.async_show_form(step_id="hub", data_schema=_hub_schema(user_input), errors=errors)

    async def async_step_import(self, user_input: dict[str, Any]) -> FlowResult:
        cleaned = _clean_device(user_input)
        try:
            info = await _validate_host(self.hass, cleaned)
        except CannotConnect as err:
            _LOGGER.error(
                "Tasmota REST YAML import failed for %s: %s", cleaned.get(CONF_HOST), err
            )
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(info["unique_id"])
        self._abort_if_unique_id_configured(updates=cleaned)
        cleaned[ENTRY_TYPE] = ENTRY_TYPE_DEVICE
        title = cleaned.get(CONF_NAME) or info["title"]
        return self.async_create_entry(title=title, data=cleaned)

    # ---- Discovery handlers ----

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
        host = discovery_info.ip
        mac = _format_mac(discovery_info.macaddress)
        return await self._async_handle_discovery(host=host, mac=mac, title=discovery_info.hostname)

    async def async_step_zeroconf(self, discovery_info: zeroconf.ZeroconfServiceInfo) -> FlowResult:
        host = (
            discovery_info.ip_address.compressed
            if hasattr(discovery_info, "ip_address") and discovery_info.ip_address
            else discovery_info.host
        )
        return await self._async_handle_discovery(host=host, mac=None, title=discovery_info.name)

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> FlowResult:
        return await self._async_handle_discovery(
            host=discovery_info[CONF_HOST],
            mac=discovery_info.get("mac"),
            title=discovery_info.get("title"),
            auto_add=bool(discovery_info.get("auto_add")),
            default_username=discovery_info.get("default_username"),
            default_password=discovery_info.get("default_password"),
        )

    async def _async_handle_discovery(
        self,
        host: str,
        mac: str | None,
        title: str | None,
        auto_add: bool = False,
        default_username: str | None = None,
        default_password: str | None = None,
    ) -> FlowResult:
        # Validate by querying the device; this also gives us the MAC reliably
        probe_input = {CONF_HOST: host}
        if default_username:
            probe_input[CONF_USERNAME] = default_username
        if default_password:
            probe_input[CONF_PASSWORD] = default_password
        try:
            info = await _validate_host(self.hass, probe_input)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="unknown")

        unique_id = info["unique_id"] or _format_mac(mac) or host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        title = title or info["title"]
        self._discovered = {
            CONF_HOST: host,
            "title": title,
            "default_username": default_username,
            "default_password": default_password,
            "auto_add": auto_add,
        }
        self.context["title_placeholders"] = {"host": host, "name": title}

        if auto_add:
            return await self._async_create_discovered_entry()

        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return await self._async_create_discovered_entry()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "host": self._discovered.get(CONF_HOST, ""),
                "name": self._discovered.get("title", ""),
            },
        )

    async def _async_create_discovered_entry(self) -> FlowResult:
        data = {
            CONF_HOST: self._discovered[CONF_HOST],
            ENTRY_TYPE: ENTRY_TYPE_DEVICE,
        }
        if self._discovered.get("default_username"):
            data[CONF_USERNAME] = self._discovered["default_username"]
        if self._discovered.get("default_password"):
            data[CONF_PASSWORD] = self._discovered["default_password"]
        return self.async_create_entry(title=self._discovered["title"], data=data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "config_entries.OptionsFlow":
        if config_entry.data.get(ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return TasmotaRestHubOptionsFlow(config_entry)
        return TasmotaRestDeviceOptionsFlow(config_entry)


class TasmotaRestDeviceOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=_clean_device(user_input))

        merged = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=2, max=300, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s"
                    )
                ),
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_ENABLED, default=merged.get(CONF_VIRTUAL_SWITCH_ENABLED, False)
                ): bool,
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_THRESHOLD,
                    default=merged.get(CONF_VIRTUAL_SWITCH_THRESHOLD, DEFAULT_VIRTUAL_THRESHOLD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=4000, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="W"
                    )
                ),
                vol.Optional(
                    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
                    default=merged.get(CONF_VIRTUAL_SWITCH_PRESS_ENTITY, ""),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="button")),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class TasmotaRestHubOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=_clean_hub(user_input))

        merged = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_hub_schema(merged))
