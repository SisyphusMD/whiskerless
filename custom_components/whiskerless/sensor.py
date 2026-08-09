"""Sensor platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
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
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from whiskerless.devices.litter_robot_4 import LitterRobot4State
from whiskerless.devices.litter_robot_4.models import litter_level_percent_from_mm

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator, WhiskerlessData
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
    "changing_filter",
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
        key="waste_drawer_level",
        translation_key="waste_drawer_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda robot: robot.waste_drawer_level,
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


@dataclass(frozen=True, kw_only=True)
class WhiskerlessDataSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor fed from activity-derived data (not the state doc)."""

    data_fn: Callable[[WhiskerlessData], StateType | datetime]
    # Event-sourced sensors restore, because the robot may not speak for hours.
    # State-sourced ones must not: their None is an active suppression, and
    # showing the last value would contradict it.
    restores: bool = True


# These facts exist ONLY in the activity stream: the local state document never
# carries cat weight, and hopper dispenses are pure events. They are also
# event-driven, so without restoring the last value every entity here would sit
# unknown from an HA restart until the next cat visit or dispense — potentially
# hours.
def _litter_percent(data: WhiskerlessData) -> StateType:
    """Litter %, against this robot's calibration when it has one.

    A percentage the firmware reports itself always wins: it is the device's own
    answer, and calibration exists only to replace our approximation of it.
    """
    robot = data.robot
    if robot.litter_level_reported or robot.litter_level_mm is None:
        return robot.litter_level
    return litter_level_percent_from_mm(
        robot.litter_level_mm, full_mm=data.litter_full_mm, empty_mm=data.litter_empty_mm
    )


DATA_SENSORS: tuple[WhiskerlessDataSensorEntityDescription, ...] = (
    WhiskerlessDataSensorEntityDescription(
        key="litter_level",
        translation_key="litter_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        data_fn=_litter_percent,
        restores=False,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="pet_weight",
        translation_key="pet_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.POUNDS,
        state_class=SensorStateClass.MEASUREMENT,
        data_fn=lambda data: data.cat_weight_lb
        if data.cat_weight_lb is not None
        else data.robot.cat_weight,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="last_cat_visit",
        translation_key="last_cat_visit",
        device_class=SensorDeviceClass.TIMESTAMP,
        data_fn=lambda data: data.last_cat_visit,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="last_hopper_dispensed",
        translation_key="last_hopper_dispensed",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.last_hopper_dispensed,
    ),
    # Seconds of settled weight (reg 0xBC). Reported even for visits too short
    # to produce a weight event, so short hop-throughs still show up here.
    WhiskerlessDataSensorEntityDescription(
        key="last_visit_duration",
        translation_key="last_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        data_fn=lambda data: data.last_visit_duration_s,
    ),
    # The hopper's own fill gauge (dispense phase-1 value): ~90 near a 90%
    # maintain target, declining monotonically as the hopper drains. Unitless
    # raw until the empty/refill anchors calibrate a scale; updates only when
    # a dispense runs.
    WhiskerlessDataSensorEntityDescription(
        key="hopper_fill",
        translation_key="hopper_fill",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.hopper_fill_raw,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        WhiskerlessSensor(coordinator, description) for description in SENSORS
    ]
    entities.extend(
        WhiskerlessDataSensor(coordinator, description) for description in DATA_SENSORS
    )
    async_add_entities(entities)


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


class WhiskerlessDataSensor(WhiskerlessEntity, RestoreSensor):
    """A Whiskerless sensor fed from activity-derived coordinator data."""

    entity_description: WhiskerlessDataSensorEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessDataSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"
        self._restored: StateType | datetime = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The NATIVE value, not the rendered state: reading last.state would
        # pick up the user's display unit (kg, minutes) and hand it back as if
        # it were pounds or seconds, re-converting on every restart.
        last = await self.async_get_last_sensor_data()
        if last is None:
            return
        value = last.native_value
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, date) and not isinstance(value, datetime):
            # No sensor here is a plain date; a cache holding one is not ours.
            return
        self._restored = value

    @property
    @override
    def native_value(self) -> StateType | datetime:
        # The robot only speaks these on an event, so hold the restored value
        # until it does rather than reading unknown for hours after a restart.
        current = self.entity_description.data_fn(self.coordinator.data)
        if current is None and self.entity_description.restores:
            return self._restored
        return current
