"""DataUpdateCoordinator for Tasmota REST."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_TIMEZONE_CMD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class TasmotaRestError(Exception):
    """Tasmota REST request failure."""


class TasmotaRestCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls a single Tasmota device over HTTP and exposes helper methods."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.configured_name: str | None = entry.data.get(CONF_NAME)
        self.username: str | None = entry.data.get(CONF_USERNAME)
        self.password: str | None = entry.data.get(CONF_PASSWORD)
        self.use_https: bool = bool(entry.data.get(CONF_USE_HTTPS, False))
        self.verify_ssl: bool = bool(entry.data.get(CONF_VERIFY_SSL, False))
        self._session: aiohttp.ClientSession = async_get_clientsession(
            hass, verify_ssl=self.verify_ssl
        )

        scan_interval = (
            entry.options.get(CONF_SCAN_INTERVAL)
            or entry.data.get(CONF_SCAN_INTERVAL)
            or DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=timedelta(seconds=int(scan_interval)),
        )

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}"

    @property
    def device_name(self) -> str:
        if self.configured_name:
            return self.configured_name
        status = (self.data or {}).get("Status") or {}
        friendly = status.get("FriendlyName")
        if isinstance(friendly, list) and friendly:
            return str(friendly[0])
        if isinstance(friendly, str):
            return friendly
        return status.get("DeviceName") or f"Tasmota {self.host}"

    @property
    def mac(self) -> str | None:
        net = (self.data or {}).get("StatusNET") or {}
        return net.get("Mac")

    @property
    def power_state(self) -> str | None:
        sts = (self.data or {}).get("StatusSTS") or {}
        return sts.get("POWER") or sts.get("POWER1")

    @property
    def energy(self) -> dict[str, Any]:
        sns = (self.data or {}).get("StatusSNS") or {}
        energy = sns.get("ENERGY") or {}
        return energy if isinstance(energy, dict) else {}

    @property
    def has_energy(self) -> bool:
        return bool(self.energy)

    @property
    def device_info(self) -> DeviceInfo:
        firmware = (self.data or {}).get("StatusFWR") or {}
        status = (self.data or {}).get("Status") or {}
        connections = set()
        if self.mac:
            connections.add(("mac", self.mac))
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.device_name,
            manufacturer="Tasmota",
            model=firmware.get("Hardware") or status.get("Module") or "Tasmota",
            sw_version=firmware.get("Version"),
            configuration_url=self.base_url,
            connections=connections,
        )

    async def _async_send(self, command: str) -> dict[str, Any]:
        """Send a Tasmota command via /cm and return parsed JSON."""
        params: dict[str, str] = {"cmnd": command}
        if self.username:
            params["user"] = self.username
        if self.password:
            params["password"] = self.password
        url = f"{self.base_url}/cm"
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                async with self._session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    text = await resp.text()
        except asyncio.TimeoutError as err:
            raise TasmotaRestError(f"Timeout contacting {self.host}") from err
        except aiohttp.ClientError as err:
            raise TasmotaRestError(f"HTTP error contacting {self.host}: {err}") from err

        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Some commands (e.g. WebLog) return non-JSON; expose as raw
            return {"raw": text}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_send("Status 0")
        except TasmotaRestError as err:
            raise UpdateFailed(str(err)) from err

    # ---- High level commands ----

    async def async_power(self, on: bool) -> dict[str, Any]:
        result = await self._async_send(f"Power {'On' if on else 'Off'}")
        if isinstance(result, dict) and "POWER" in result:
            data = dict(self.data or {})
            sts = dict(data.get("StatusSTS") or {})
            sts["POWER"] = result["POWER"]
            data["StatusSTS"] = sts
            self.async_set_updated_data(data)
        else:
            await self.async_request_refresh()
        return result

    async def async_set_timer(self, timer_number: int, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"))
        return await self._async_send(f"Timer{timer_number} {body}")

    async def async_disable_all_timers(self, count: int = 6) -> dict[str, Any]:
        cmds = "; ".join(f'Timer{i} {{"Enable":0}}' for i in range(1, count + 1))
        return await self._async_send(f"Backlog0 {cmds}")

    async def async_get_timers(self) -> dict[str, Any]:
        return await self._async_send("Timers")

    async def async_set_timezone(self, command: str | None = None) -> dict[str, Any]:
        return await self._async_send(command or DEFAULT_TIMEZONE_CMD)

    async def async_send_command(self, command: str) -> dict[str, Any]:
        return await self._async_send(command)

    async def async_backlog(self, command: str) -> dict[str, Any]:
        cmd = command.strip()
        if not cmd.lower().startswith(("backlog0", "backlog")):
            cmd = f"Backlog0 {cmd}"
        return await self._async_send(cmd)

    async def async_restart(self, restart_type: int = 1) -> dict[str, Any]:
        return await self._async_send(f"Restart {restart_type}")

    async def async_normalize_time(self) -> dict[str, Any]:
        """Push current local time from HA to Tasmota."""
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%dT%H:%M:%S")
        return await self._async_send(f"Time {time_str}")
