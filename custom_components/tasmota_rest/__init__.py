"""Tasmota REST integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICES,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    CONF_VIRTUAL_SWITCH_ENABLED,
    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
    CONF_VIRTUAL_SWITCH_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VIRTUAL_THRESHOLD,
    DOMAIN,
    PLATFORMS,
    SERVICE_BACKLOG,
    SERVICE_DISABLE_ALL_TIMERS,
    SERVICE_GET_TIMERS,
    SERVICE_NORMALIZE_TIME,
    SERVICE_POWER_OFF,
    SERVICE_POWER_ON,
    SERVICE_RESTART,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_TIMER,
    SERVICE_SET_TIMEZONE,
)
from .coordinator import TasmotaRestCoordinator, TasmotaRestError

_LOGGER = logging.getLogger(__name__)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
        vol.Optional(CONF_USE_HTTPS, default=False): cv.boolean,
        vol.Optional(CONF_VERIFY_SSL, default=False): cv.boolean,
        vol.Optional(CONF_VIRTUAL_SWITCH_ENABLED, default=False): cv.boolean,
        vol.Optional(CONF_VIRTUAL_SWITCH_THRESHOLD, default=DEFAULT_VIRTUAL_THRESHOLD): vol.Coerce(float),
        vol.Optional(CONF_VIRTUAL_SWITCH_PRESS_ENTITY): cv.entity_id,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {vol.Required(CONF_DEVICES): vol.All(cv.ensure_list, [DEVICE_SCHEMA])}
        )
    },
    extra=vol.ALLOW_EXTRA,
)


# ---- Service schemas ----

_TARGET_SCHEMA = {
    vol.Optional("device_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("entity_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("area_id"): vol.Any(cv.string, [cv.string]),
}

SET_TIMER_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Required("timer_number"): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
        vol.Optional("enable", default=True): cv.boolean,
        vol.Optional("time"): cv.string,
        vol.Optional("window", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=15)),
        vol.Optional("days", default="1111111"): vol.Match(r"^[01]{7}$"),
        vol.Optional("repeat", default=True): cv.boolean,
        vol.Optional("output", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
        vol.Optional("action", default=1): vol.All(vol.Coerce(int), vol.Range(min=0, max=3)),
    }
)

DISABLE_ALL_TIMERS_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Optional("count", default=6): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
    }
)

GET_TIMERS_SCHEMA = vol.Schema({**_TARGET_SCHEMA})

SET_TIMEZONE_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Optional("command"): cv.string,
    }
)

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Required("command"): cv.string,
    }
)

BACKLOG_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Required("command"): cv.string,
    }
)

RESTART_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Optional("type", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
    }
)

NORMALIZE_TIME_SCHEMA = vol.Schema({**_TARGET_SCHEMA})

POWER_SCHEMA = vol.Schema({**_TARGET_SCHEMA})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration. Imports YAML devices into config entries."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_services(hass)

    domain_config = config.get(DOMAIN)
    if domain_config:
        for device in domain_config.get(CONF_DEVICES, []):
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=dict(device)
                )
            )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tasmota REST from a config entry."""
    coordinator = TasmotaRestCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---- Service registration ----

@callback
def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_TIMER):
        return

    def _resolve_coordinators(call: ServiceCall) -> list[TasmotaRestCoordinator]:
        coords: list[TasmotaRestCoordinator] = []
        seen: set[str] = set()

        device_ids = call.data.get("device_id") or []
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        entity_ids = call.data.get("entity_id") or []
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        device_registry = dr.async_get(hass)
        entity_registry = None

        if entity_ids:
            from homeassistant.helpers import entity_registry as er
            entity_registry = er.async_get(hass)
            for entity_id in entity_ids:
                ent = entity_registry.async_get(entity_id)
                if ent and ent.device_id and ent.device_id not in device_ids:
                    device_ids = list(device_ids) + [ent.device_id]

        for device_id in device_ids:
            device = device_registry.async_get(device_id)
            if not device:
                continue
            for entry_id in device.config_entries:
                if entry_id in seen:
                    continue
                coord = hass.data.get(DOMAIN, {}).get(entry_id)
                if coord is not None:
                    seen.add(entry_id)
                    coords.append(coord)
        return coords

    def _require_coordinators(call: ServiceCall) -> list[TasmotaRestCoordinator]:
        coords = _resolve_coordinators(call)
        if not coords:
            raise ServiceValidationError(
                "No Tasmota REST devices selected. Use the target picker to "
                "select one or more Tasmota REST devices."
            )
        return coords

    async def _run_all(coords, awaitable_factory):
        errors: list[str] = []
        for coord in coords:
            try:
                await awaitable_factory(coord)
            except TasmotaRestError as err:
                errors.append(f"{coord.host}: {err}")
        if errors:
            raise HomeAssistantError("; ".join(errors))

    async def handle_set_timer(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        timer_number: int = call.data["timer_number"]
        payload: dict[str, Any] = {"Enable": 1 if call.data.get("enable", True) else 0}
        if "time" in call.data:
            payload["Time"] = call.data["time"]
        payload["Window"] = int(call.data.get("window", 0))
        payload["Days"] = str(call.data.get("days", "1111111"))
        payload["Repeat"] = 1 if call.data.get("repeat", True) else 0
        payload["Output"] = int(call.data.get("output", 1))
        payload["Action"] = int(call.data.get("action", 1))
        await _run_all(coords, lambda c: c.async_set_timer(timer_number, payload))

    async def handle_disable_all_timers(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        count = int(call.data.get("count", 6))
        await _run_all(coords, lambda c: c.async_disable_all_timers(count))

    async def handle_get_timers(call: ServiceCall) -> dict[str, Any]:
        coords = _require_coordinators(call)
        results: dict[str, Any] = {}
        for coord in coords:
            try:
                results[coord.host] = await coord.async_get_timers()
            except TasmotaRestError as err:
                results[coord.host] = {"error": str(err)}
        return {"devices": results}

    async def handle_set_timezone(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        cmd = call.data.get("command")
        await _run_all(coords, lambda c: c.async_set_timezone(cmd))

    async def handle_send_command(call: ServiceCall) -> dict[str, Any]:
        coords = _require_coordinators(call)
        command: str = call.data["command"]
        results: dict[str, Any] = {}
        for coord in coords:
            try:
                results[coord.host] = await coord.async_send_command(command)
            except TasmotaRestError as err:
                results[coord.host] = {"error": str(err)}
        return {"devices": results}

    async def handle_backlog(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        command: str = call.data["command"]
        await _run_all(coords, lambda c: c.async_backlog(command))

    async def handle_restart(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        restart_type = int(call.data.get("type", 1))
        await _run_all(coords, lambda c: c.async_restart(restart_type))

    async def handle_normalize_time(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        await _run_all(coords, lambda c: c.async_normalize_time())

    async def handle_power_on(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        await _run_all(coords, lambda c: c.async_power(True))

    async def handle_power_off(call: ServiceCall) -> None:
        coords = _require_coordinators(call)
        await _run_all(coords, lambda c: c.async_power(False))

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TIMER, handle_set_timer, schema=SET_TIMER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISABLE_ALL_TIMERS, handle_disable_all_timers, schema=DISABLE_ALL_TIMERS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_TIMERS,
        handle_get_timers,
        schema=GET_TIMERS_SCHEMA,
        supports_response="optional",
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TIMEZONE, handle_set_timezone, schema=SET_TIMEZONE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        handle_send_command,
        schema=SEND_COMMAND_SCHEMA,
        supports_response="optional",
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BACKLOG, handle_backlog, schema=BACKLOG_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESTART, handle_restart, schema=RESTART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_NORMALIZE_TIME, handle_normalize_time, schema=NORMALIZE_TIME_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_POWER_ON, handle_power_on, schema=POWER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_POWER_OFF, handle_power_off, schema=POWER_SCHEMA
    )
