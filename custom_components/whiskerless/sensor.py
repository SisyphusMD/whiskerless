"""Sensor platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from whiskerless.devices.litter_robot_4 import LitterRobot4State

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0

# Only the known status slugs are valid ENUM states; anything else reads unknown.
STATUS_OPTIONS = [
    "ready",
    "cat_detected",
    "clean_cycle",
    "empty_cycle",
    "cat_sensor_timing",
    "bonnet_removed",
    "powering_up",
    "powering_down",
    "off",
]


@dataclass(frozen=True, kw_only=True)
class WhiskerlessSensorEntityDescription(SensorEntityDescription):
    """Describes a Whiskerless sensor."""

    value_fn: Callable[[LitterRobot4State], StateType]


def _status(robot: LitterRobot4State) -> StateType:
    return robot.robot_status if robot.robot_status in STATUS_OPTIONS else None


SENSORS: tuple[WhiskerlessSensorEntityDescription, ...] = (
    WhiskerlessSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=_status,
    ),
    WhiskerlessSensorEntityDescription(
        key="litter_level",
        translation_key="litter_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda robot: robot.litter_level,
    ),
    WhiskerlessSensorEntityDescription(
        key="waste_drawer_level",
        translation_key="waste_drawer_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda robot: robot.waste_drawer_level,
    ),
    WhiskerlessSensorEntityDescription(
        key="pet_weight",
        translation_key="pet_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda robot: robot.cat_weight,
    ),
    WhiskerlessSensorEntityDescription(
        key="clean_cycle_count",
        translation_key="clean_cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda robot: robot.odometer_clean_cycles,
    ),
    WhiskerlessSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda robot: robot.wifi_rssi,
    ),
    WhiskerlessSensorEntityDescription(
        key="litter_level_mm",
        translation_key="litter_level_mm",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda robot: robot.litter_level_mm,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless sensors."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessSensor(coordinator, description) for description in SENSORS)


class WhiskerlessSensor(WhiskerlessEntity, SensorEntity):
    """A Whiskerless sensor."""

    entity_description: WhiskerlessSensorEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self._robot)
