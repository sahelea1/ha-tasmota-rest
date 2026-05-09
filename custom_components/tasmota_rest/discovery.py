"""LAN scanning, AP provisioning and WiFi-environment scanning for Tasmota REST.

Three workflows are implemented:

* ``async_scan_lan``  - HTTP-probe each host on the configured (or auto-detected)
  subnet(s) for a Tasmota ``Status 0`` response. Hits trigger an
  ``integration_discovery`` flow which - depending on ``auto_add_discovered`` -
  silently creates a config entry or surfaces a confirmation step in the UI.
* ``async_try_provision_ap`` - if the configured AP IP (default 192.168.4.1) is
  reachable AND responds with a Tasmota signature, push the stored WiFi
  credentials via ``Backlog`` and reboot the device. Once it joins the home
  network the LAN scanner picks it up.
* ``async_scan_wifi_environment`` - best-effort: shells out to ``nmcli`` (or
  ``iw``) to list nearby AP SSIDs, filters by the configured pattern
  (``tasmota`` by default) and surfaces a persistent notification listing the
  candidates. Silently no-ops if the tool isn't available.

Everything is debounced and bounded so it cannot saturate the network stack.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp
import async_timeout

from homeassistant.components import network
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_AP_AUTO_PROVISION,
    CONF_AP_IP,
    CONF_AP_SSID_PATTERN,
    CONF_DEFAULT_PASSWORD,
    CONF_DEFAULT_USERNAME,
    CONF_HOSTNAME_TEMPLATE,
    CONF_SCAN_INTERVAL_MIN,
    CONF_SCAN_SUBNETS,
    CONF_WIFI_PASSWORD,
    CONF_WIFI_PASSWORD2,
    CONF_WIFI_SCAN_ENABLED,
    CONF_WIFI_SSID,
    CONF_WIFI_SSID2,
    DEFAULT_AP_IP,
    DEFAULT_AP_SSID_PATTERN,
    DEFAULT_PROBE_TIMEOUT,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Cap concurrency so a /24 sweep does not saturate aiohttp's connection pool
_PROBE_CONCURRENCY = 32
# Refuse to brute-force anything bigger than a /22
_MAX_HOSTS_PER_SUBNET = 1024


def _get_hub_entry(hass: HomeAssistant) -> ConfigEntry | None:
    from .const import ENTRY_TYPE, ENTRY_TYPE_HUB

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return entry
    return None


def _opt(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def _looks_like_tasmota(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return "Status" in payload and "StatusFWR" in payload


def _extract_mac(payload: dict[str, Any]) -> str | None:
    net_info = payload.get("StatusNET") or {}
    return net_info.get("Mac")


def _format_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    cleaned = mac.replace(":", "").replace("-", "").upper()
    if len(cleaned) != 12:
        return mac.upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def _device_title(payload: dict[str, Any], host: str) -> str:
    status = payload.get("Status") or {}
    friendly = status.get("FriendlyName")
    if isinstance(friendly, list) and friendly:
        return str(friendly[0])
    if isinstance(friendly, str):
        return friendly
    return status.get("DeviceName") or host


def _is_ap_signature(payload: dict[str, Any]) -> bool:
    """Return True if the device looks like a Tasmota in AP/setup mode."""
    if not _looks_like_tasmota(payload):
        return False
    status = payload.get("Status") or {}
    sts = payload.get("StatusSTS") or {}
    wifi = sts.get("Wifi") or {}
    # In AP / WIFICONFIG_MANAGER mode, AP1 SSID is empty and Wifi.SSId is empty.
    ap_ssid_blank = not status.get("SSId") and not wifi.get("SSId")
    return bool(ap_ssid_blank)


class TasmotaDiscoveryHub:
    """Owns the periodic scan loop tied to the hub config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsub_interval = None
        self._scan_lock = asyncio.Lock()
        self.last_aps: list[str] = []
        self.last_lan_count: int = 0
        self._closing = False

    @callback
    def _option(self, key: str, default: Any = None) -> Any:
        return _opt(self.entry, key, default)

    async def async_start(self) -> None:
        interval_min = max(1, int(self._option(CONF_SCAN_INTERVAL_MIN, DEFAULT_SCAN_MINUTES)))
        # Kick off an initial sweep without blocking setup
        self.hass.async_create_task(self._async_run_cycle())
        self._unsub_interval = async_track_time_interval(
            self.hass, self._async_interval_callback, timedelta(minutes=interval_min)
        )
        _LOGGER.debug("Tasmota discovery hub scheduled every %d min", interval_min)

    async def async_stop(self) -> None:
        self._closing = True
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_interval_callback(self, _now) -> None:
        await self._async_run_cycle()

    async def _async_run_cycle(self) -> None:
        if self._closing:
            return
        if self._scan_lock.locked():
            return  # previous cycle still running
        async with self._scan_lock:
            try:
                await self.async_scan_lan()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("LAN scan failed")
            try:
                if self._option(CONF_AP_AUTO_PROVISION, True):
                    await self.async_try_provision_ap()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("AP provisioning attempt failed")
            try:
                if self._option(CONF_WIFI_SCAN_ENABLED, True):
                    await self.async_scan_wifi_environment()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("WiFi environment scan failed")

    # ----------------- LAN HTTP scanner -----------------

    async def async_scan_lan(self) -> int:
        subnets_opt = self._option(CONF_SCAN_SUBNETS) or []
        if isinstance(subnets_opt, str):
            subnets_opt = [s.strip() for s in subnets_opt.split(",") if s.strip()]
        subnets = subnets_opt or await self._auto_subnets()

        total_hits = 0
        seen_ips: set[str] = set()
        for subnet_str in subnets:
            try:
                net = ipaddress.ip_network(subnet_str, strict=False)
            except ValueError:
                _LOGGER.warning("Ignoring invalid subnet: %s", subnet_str)
                continue
            if net.num_addresses > _MAX_HOSTS_PER_SUBNET:
                _LOGGER.warning(
                    "Subnet %s is too large (%d hosts); cap is %d",
                    subnet_str, net.num_addresses, _MAX_HOSTS_PER_SUBNET,
                )
                continue
            hits = await self._scan_subnet(net, seen_ips)
            total_hits += hits

        self.last_lan_count = total_hits
        return total_hits

    async def _auto_subnets(self) -> list[str]:
        try:
            adapters = await network.async_get_adapters(self.hass)
        except Exception:  # noqa: BLE001
            return []
        result: list[str] = []
        for adapter in adapters:
            if not adapter.get("enabled"):
                continue
            for ip_info in adapter.get("ipv4", []):
                addr = ip_info["address"]
                prefix = ip_info["network_prefix"]
                if prefix < 24:
                    prefix = 24  # cap to /24 so we never sweep a corporate /16
                result.append(f"{addr}/{prefix}")
        return result

    async def _scan_subnet(self, net: ipaddress._BaseNetwork, seen: set[str]) -> int:
        session = async_get_clientsession(self.hass)
        sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

        async def _probe(ip_str: str) -> tuple[str, dict[str, Any] | None]:
            async with sem:
                payload = await self._probe_host(session, ip_str)
            return ip_str, payload

        tasks = []
        for host_ip in net.hosts():
            ip_str = str(host_ip)
            if ip_str in seen:
                continue
            seen.add(ip_str)
            tasks.append(_probe(ip_str))

        hits = 0
        for coro in asyncio.as_completed(tasks):
            ip_str, payload = await coro
            if payload is None:
                continue
            hits += 1
            self._handle_lan_hit(ip_str, payload)
        return hits

    async def _probe_host(self, session: aiohttp.ClientSession, ip: str) -> dict[str, Any] | None:
        params: dict[str, str] = {"cmnd": "Status 0"}
        user = self._option(CONF_DEFAULT_USERNAME)
        password = self._option(CONF_DEFAULT_PASSWORD)
        if user:
            params["user"] = user
        if password:
            params["password"] = password
        try:
            async with async_timeout.timeout(DEFAULT_PROBE_TIMEOUT):
                async with session.get(f"http://{ip}/cm", params=params) as resp:
                    if resp.status != 200:
                        return None
                    text = await resp.text()
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data if _looks_like_tasmota(data) else None

    @callback
    def _handle_lan_hit(self, ip: str, payload: dict[str, Any]) -> None:
        mac = _format_mac(_extract_mac(payload))
        unique_id = mac or ip
        existing = next(
            (
                e
                for e in self.hass.config_entries.async_entries(DOMAIN)
                if e.unique_id == unique_id
            ),
            None,
        )
        if existing is not None:
            if existing.data.get(CONF_HOST) != ip:
                self.hass.config_entries.async_update_entry(
                    existing, data={**existing.data, CONF_HOST: ip}
                )
            return

        from .const import CONF_AUTO_ADD_DISCOVERED

        discovery_data = {
            CONF_HOST: ip,
            "mac": mac,
            "title": _device_title(payload, ip),
            "auto_add": bool(self._option(CONF_AUTO_ADD_DISCOVERED, False)),
            "default_username": self._option(CONF_DEFAULT_USERNAME),
            "default_password": self._option(CONF_DEFAULT_PASSWORD),
        }
        discovery_flow.async_create_flow(
            self.hass,
            DOMAIN,
            {"source": SOURCE_INTEGRATION_DISCOVERY},
            discovery_data,
        )

    # ----------------- AP provisioning -----------------

    async def async_try_provision_ap(self) -> bool:
        ssid = self._option(CONF_WIFI_SSID)
        password = self._option(CONF_WIFI_PASSWORD)
        if not ssid:
            return False
        ap_ip = self._option(CONF_AP_IP, DEFAULT_AP_IP)
        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(DEFAULT_PROBE_TIMEOUT):
                async with session.get(f"http://{ap_ip}/cm", params={"cmnd": "Status 0"}) as resp:
                    if resp.status != 200:
                        return False
                    text = await resp.text()
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return False
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not _is_ap_signature(payload):
            return False

        await self.async_provision(
            ap_ip,
            ssid,
            password,
            ssid2=self._option(CONF_WIFI_SSID2),
            password2=self._option(CONF_WIFI_PASSWORD2),
            hostname=self._render_hostname(payload),
            already_validated=True,
        )
        _LOGGER.info("Auto-provisioned Tasmota at %s with SSID '%s'", ap_ip, ssid)
        return True

    def _render_hostname(self, payload: dict[str, Any]) -> str | None:
        template = self._option(CONF_HOSTNAME_TEMPLATE)
        if not template:
            return None
        mac = _extract_mac(payload) or ""
        suffix = mac.replace(":", "").lower()[-6:] if mac else ""
        return template.replace("{mac}", suffix).replace("{MAC}", suffix.upper())

    async def async_provision(
        self,
        host: str,
        ssid: str,
        password: str | None,
        ssid2: str | None = None,
        password2: str | None = None,
        hostname: str | None = None,
        already_validated: bool = False,
    ) -> str:
        """Push WiFi creds to a reachable Tasmota and reboot."""
        if not already_validated:
            session = async_get_clientsession(self.hass)
            try:
                async with async_timeout.timeout(DEFAULT_PROBE_TIMEOUT):
                    async with session.get(
                        f"http://{host}/cm", params={"cmnd": "Status 0"}
                    ) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"Tasmota at {host} not reachable (HTTP {resp.status})")
                        text = await resp.text()
            except (asyncio.TimeoutError, aiohttp.ClientError) as err:
                raise RuntimeError(f"Tasmota at {host} not reachable: {err}") from err
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as err:
                raise RuntimeError(f"Tasmota at {host} returned invalid JSON") from err
            if not _looks_like_tasmota(payload):
                raise RuntimeError(f"Host {host} does not look like a Tasmota device")

        cmds: list[str] = []
        cmds.append(f"SSID1 {_quote_arg(ssid)}")
        cmds.append(f"Password1 {_quote_arg(password) if password else ''}")
        if ssid2:
            cmds.append(f"SSID2 {_quote_arg(ssid2)}")
            cmds.append(f"Password2 {_quote_arg(password2) if password2 else ''}")
        if hostname:
            cmds.append(f"Hostname {hostname}")
        cmds.append("Restart 1")
        full = "Backlog0 " + "; ".join(cmds)

        session = async_get_clientsession(self.hass)
        async with async_timeout.timeout(10):
            async with session.get(f"http://{host}/cm", params={"cmnd": full}) as resp:
                resp.raise_for_status()
                return await resp.text()

    # ----------------- WiFi environment scan -----------------

    async def async_scan_wifi_environment(self) -> list[str]:
        """Best-effort: list nearby AP SSIDs matching the configured pattern."""
        text = await _exec_text(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
        if text is None:
            text = await _exec_text(["iwlist", "scanning"])
        if text is None:
            self.last_aps = []
            return []

        pattern = self._option(CONF_AP_SSID_PATTERN, DEFAULT_AP_SSID_PATTERN).lower()
        aps: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if "ESSID:" in line:
                # iwlist output: ESSID:"name"
                ssid = line.split("ESSID:", 1)[1].strip().strip('"')
            else:
                ssid = line.split(":", 1)[0]
            if not ssid or ssid in aps:
                continue
            if pattern in ssid.lower():
                aps.append(ssid)

        self.last_aps = aps
        if aps:
            await self._notify_aps(aps)
        else:
            await self._clear_ap_notification()
        return aps

    async def _notify_aps(self, aps: list[str]) -> None:
        ssid = self._option(CONF_WIFI_SSID) or "<unset>"
        message = (
            f"Detected nearby Tasmota access point(s): **{', '.join(aps)}**.\n\n"
            f"They will join your WiFi as soon as they can reach a Tasmota AP "
            f"reachable from Home Assistant. Configured target SSID: **{ssid}**.\n\n"
            "If your HA host has a route to the AP (e.g. 192.168.4.1 reachable), "
            "the integration will provision them automatically. Otherwise, connect a "
            "device to the AP and call `tasmota_rest.provision_ap`."
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"{DOMAIN}_ap_detected",
                "title": "Tasmota AP detected",
                "message": message,
            },
            blocking=False,
        )

    async def _clear_ap_notification(self) -> None:
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"{DOMAIN}_ap_detected"},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            pass


def _quote_arg(value: str) -> str:
    """Escape single token for a Tasmota Backlog command."""
    if not value:
        return '""'
    if any(c in value for c in (" ", ";", '"', "'")):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


async def _exec_text(argv: list[str]) -> str | None:
    """Run a subprocess; return decoded stdout or None if it fails."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode("utf-8", errors="ignore")
