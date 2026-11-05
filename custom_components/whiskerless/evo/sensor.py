"""EVO sensors: status, what the panel shows, and the raw readings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState, const

from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoSensorEntityDescription(SensorEntityDescription):
    """Describes an EVO sensor."""

    value_fn: Callable[[LitterRobotEvoState], str | int | float | None]


SENSORS: tuple[EvoSensorEntityDescription, ...] = (
    EvoSensorEntityDescription(
        key="robot_status",
        translation_key="robot_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(dict.fromkeys(const.ROBOT_STATUS.values())),
        value_fn=lambda robot: robot.robot_status,
    ),
    EvoSensorEntityDescription(
        key="panel_display",
        translation_key="panel_display",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=list(dict.fromkeys(const.DISPLAY_CODES.values())),
        value_fn=lambda robot: robot.display,
    ),
    # From the robot's `usage` event, which reports hundredths of a pound.
    EvoSensorEntityDescription(
        key="pet_weight",
        translation_key="pet_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda robot: robot.last_weight_lb,
    ),
    EvoSensorEntityDescription(
        key="power_cycle_count",
        translation_key="power_cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda robot: robot.odometer_power_cycles,
    ),
    EvoSensorEntityDescription(
        key="empty_cycle_count",
        translation_key="empty_cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda robot: robot.odometer_empty_cycles,
    ),
    # Raw, unitless: the weight sensor's scale is not yet known.
    EvoSensorEntityDescription(
        key="weight_raw",
        translation_key="weight_raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda robot: robot.weight_raw,
    ),
    EvoSensorEntityDescription(
        key="drawer_counter",
        translation_key="drawer_counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda robot: robot.drawer_counter,
    ),
    EvoSensorEntityDescription(
        key="cycle_step",
        translation_key="cycle_step",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda robot: robot.cycle_step,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO sensors."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoSensor(coordinator, description) for description in SENSORS)


class EvoSensor(WhiskerlessEvoEntity, SensorEntity):
    """An EVO sensor."""

    entity_description: EvoSensorEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoSensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> str | int | float | None:
        return self.entity_description.value_fn(self._robot)
