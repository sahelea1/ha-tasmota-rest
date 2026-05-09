"""Switch platform for Tasmota REST."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_VIRTUAL_SWITCH_ENABLED,
    CONF_VIRTUAL_SWITCH_PRESS_ENTITY,
    CONF_VIRTUAL_SWITCH_THRESHOLD,
    DEFAULT_VIRTUAL_THRESHOLD,
    DOMAIN,
)
from .coordinator import TasmotaRestCoordinator, TasmotaRestError

_LOGGER = logging.getLogger(__name__)


def _opt(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TasmotaRestCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [TasmotaRestPowerSwitch(coordinator, entry)]

    if _opt(entry, CONF_VIRTUAL_SWITCH_ENABLED, False):
        entities.append(TasmotaRestVirtualSwitch(coordinator, entry, hass))

    async_add_entities(entities)


class _BaseTasmotaSwitch(CoordinatorEntity[TasmotaRestCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TasmotaRestCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return self.coordinator.device_info


class TasmotaRestPowerSwitch(_BaseTasmotaSwitch):
    """Primary relay switch backed by the Tasmota Power command."""

    _attr_name = None  # entity name == device name
    _attr_icon = "mdi:power-socket-eu"

    def __init__(self, coordinator: TasmotaRestCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_power"

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.power_state
        if state is None:
            return None
        return state == "ON"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.power_state is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_power(True)
        except TasmotaRestError as err:
            _LOGGER.error("Failed to turn on %s: %s", self.coordinator.host, err)

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_power(False)
        except TasmotaRestError as err:
            _LOGGER.error("Failed to turn off %s: %s", self.coordinator.host, err)


class TasmotaRestVirtualSwitch(_BaseTasmotaSwitch):
    """Virtual on/off switch driven by power-draw threshold.

    Mirrors the manual Dehumidifier Virtual switch: state is derived from
    the Tasmota power reading; turn_on / turn_off press a configured button
    entity (e.g. a Tuya push button) only when the desired state differs.
    """

    _attr_name = "Virtual"
    _attr_icon = "mdi:toggle-switch"

    def __init__(
        self,
        coordinator: TasmotaRestCoordinator,
        entry: ConfigEntry,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(coordinator, entry)
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_virtual"

    @property
    def _threshold(self) -> float:
        return float(_opt(self._entry, CONF_VIRTUAL_SWITCH_THRESHOLD, DEFAULT_VIRTUAL_THRESHOLD))

    @property
    def _press_entity(self) -> str | None:
        ent = _opt(self._entry, CONF_VIRTUAL_SWITCH_PRESS_ENTITY, None)
        return ent or None

    @property
    def _power_w(self) -> float | None:
        try:
            value = self.coordinator.energy.get("Power")
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def is_on(self) -> bool | None:
        power = self._power_w
        if power is None:
            return None
        return power > self._threshold

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._power_w is not None

    async def _press_and_refresh(self) -> None:
        press_entity = self._press_entity
        if not press_entity:
            _LOGGER.warning(
                "Virtual switch on %s has no button entity configured",
                self.coordinator.host,
            )
            return
        await self._hass.services.async_call(
            "button", "press", {"entity_id": press_entity}, blocking=True
        )
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on:
            return
        await self._press_and_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on is False:
            return
        await self._press_and_refresh()
