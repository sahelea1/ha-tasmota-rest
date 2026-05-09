"""Sensor platform for Tasmota REST."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TasmotaRestCoordinator


@dataclass(frozen=True)
class TasmotaRestSensorDescription(SensorEntityDescription):
    """Describe a Tasmota REST sensor with a value extractor."""

    value_fn: Callable[[TasmotaRestCoordinator], Any] | None = None
    available_fn: Callable[[TasmotaRestCoordinator], bool] | None = None


def _energy_value(field: str) -> Callable[[TasmotaRestCoordinator], float | None]:
    def _inner(coord: TasmotaRestCoordinator) -> float | None:
        value = coord.energy.get(field)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return _inner


def _energy_available(coord: TasmotaRestCoordinator) -> bool:
    return coord.has_energy


SENSOR_TYPES: tuple[TasmotaRestSensorDescription, ...] = (
    TasmotaRestSensorDescription(
        key="state",
        translation_key="state",
        name="State",
        icon="mdi:power",
        value_fn=lambda c: c.power_state,
        available_fn=lambda c: c.power_state is not None,
    ),
    TasmotaRestSensorDescription(
        key="power",
        translation_key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        value_fn=_energy_value("Power"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="apparent_power",
        translation_key="apparent_power",
        name="Apparent Power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_energy_value("ApparentPower"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="reactive_power",
        translation_key="reactive_power",
        name="Reactive Power",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="var",
        entity_registry_enabled_default=False,
        value_fn=_energy_value("ReactivePower"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="current",
        translation_key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=3,
        value_fn=_energy_value("Current"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="voltage",
        translation_key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        value_fn=_energy_value("Voltage"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="power_factor",
        translation_key="power_factor",
        name="Power Factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=None,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=_energy_value("Factor"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="energy_today",
        translation_key="energy_today",
        name="Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=_energy_value("Today"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="energy_yesterday",
        translation_key="energy_yesterday",
        name="Energy Yesterday",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
        value_fn=_energy_value("Yesterday"),
        available_fn=_energy_available,
    ),
    TasmotaRestSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        name="Energy Total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=_energy_value("Total"),
        available_fn=_energy_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TasmotaRestCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [TasmotaRestSensor(coordinator, entry, desc) for desc in SENSOR_TYPES]
    async_add_entities(entities)


class TasmotaRestSensor(CoordinatorEntity[TasmotaRestCoordinator], SensorEntity):
    """Generic Tasmota REST sensor described by SENSOR_TYPES."""

    _attr_has_entity_name = True
    entity_description: TasmotaRestSensorDescription

    def __init__(
        self,
        coordinator: TasmotaRestCoordinator,
        entry: ConfigEntry,
        description: TasmotaRestSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def native_value(self) -> Any:
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        check = self.entity_description.available_fn
        if check is None:
            return True
        return check(self.coordinator)
