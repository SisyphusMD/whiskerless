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

from whiskerless.devices.litter_robot_4 import LitterRobot4State, derive
from whiskerless.devices.litter_robot_4.calibration import hopper_percent_provisional
from whiskerless.devices.litter_robot_4.models import (
    LITTER_DEFAULT_FULL_MM,
    litter_level_percent_from_mm,
)

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator, WhiskerlessData
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0

# Only the known status slugs are valid ENUM states; anything else reads unknown.
STATUS_OPTIONS = [
    "ready",
    "cat_detected",
    "clean_cycle",
    "empty_cycle",
    "power_up_cycle",
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
    # Extra attributes, e.g. whether a value is a calibration or a default.
    attributes_fn: Callable[[WhiskerlessData], dict[str, str] | None] | None = None


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


def _hopper_level(data: WhiskerlessData) -> StateType:
    """The gauge as a percentage: measured once this unit's floor is confirmed,
    and a display-only estimate against the typical band before that."""
    measured = derive.hopper_level_percent(data.derived)
    if measured is not None:
        return measured
    raw = data.derived.hopper_fill_raw
    return None if raw is None else hopper_percent_provisional(raw)


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
        # Activity only. The state document's `catWeight` carries the cloud's field
        # NAME with the firmware's raw value, and no captured robot has ever emitted
        # it, so whether it needs the activity register's ÷100 is untested — falling
        # back to it would risk reporting a 12 lb cat as 1200 lb.
        # Gated: one live 1.1.75 robot has never emitted a weight in 30 h of
        # visits, and there this would be a permanent unknown.
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.cat_weight_lb,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="last_cat_visit",
        translation_key="last_cat_visit",
        device_class=SensorDeviceClass.TIMESTAMP,
        # Gated like the rest of the event sensors, but stamped from the
        # occupancy transition as well as weight/duration events, so it enables
        # at the first visit on every robot.
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.last_cat_visit,
    ),
    # Register 0x56 reports that the drawer moved but not which way, and a read
    # answers the same value in or out — so "when it was last serviced" is the
    # whole of what this signal supports. A removed/seated boolean was tried and
    # was wrong on real pulls.
    WhiskerlessDataSensorEntityDescription(
        key="waste_drawer_last_moved",
        translation_key="waste_drawer_last_moved",
        device_class=SensorDeviceClass.TIMESTAMP,
        # Gated: 0x56 has never been observed on 1.1.75 — a real drawer
        # emptying there left no event — so this may never fire on some
        # firmware.
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.drawer_last_moved,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="last_hopper_dispensed",
        translation_key="last_hopper_dispensed",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.last_hopper_dispensed,
    ),
    # Seconds of settled weight (reg 0xBC). Reported even for visits too short
    # to produce a weight event, so short hop-throughs still show up here.
    # Ships disabled and enables itself on the first duration, like the hopper
    # entities: not every robot emits this register — two on the same ESP build
    # sit either side of it (the split tracks the main-board version) — so it
    # would otherwise read unknown for the life of a robot that lacks it.
    WhiskerlessDataSensorEntityDescription(
        key="last_visit_duration",
        translation_key="last_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.last_visit_duration_s,
    ),
    # The hopper's own fill gauge (dispense phase-1 value): ~90 near a 90%
    # maintain target, declining monotonically as the hopper drains. Unitless
    # raw until the empty/refill anchors calibrate a scale; updates only when
    # a dispense runs.
    # The calibration buttons are otherwise silent on success: a button's only
    # state is when it was last pressed. Surfacing the stored reference makes the
    # press visibly do something, and shows whether this robot is calibrated at all.
    WhiskerlessDataSensorEntityDescription(
        key="litter_reference",
        translation_key="litter_reference",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # An uncalibrated robot runs on the approximation curve's anchor, and
        # showing that anchor (labelled) beats reading unknown until someone
        # presses a calibration button.
        data_fn=lambda data: (
            data.litter_reference_mm
            if data.litter_reference_mm is not None
            else LITTER_DEFAULT_FULL_MM
        ),
        attributes_fn=lambda data: {
            "source": "calibrated" if data.litter_reference_mm is not None else "default"
        },
        restores=False,
    ),
    # The percentage the raw gauge means on THIS robot once its floor has been
    # learned; before that, a display-only estimate against the typical band,
    # labelled via the source attribute.
    WhiskerlessDataSensorEntityDescription(
        key="hopper_level",
        translation_key="hopper_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        data_fn=_hopper_level,
        attributes_fn=lambda data: {
            "source": "measured" if derive.hopper_level_percent(data.derived) is not None
            else "estimate"
        },
        # Never restored. This is unknown both when there is no reading and when
        # the learned scale is not yet trusted, and resurrecting an old
        # percentage in the second case would show a number derived from a scale
        # we have just decided is wrong. The raw gauge beside it does restore.
        restores=False,
    ),
    WhiskerlessDataSensorEntityDescription(
        key="hopper_fill",
        translation_key="hopper_fill",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        data_fn=lambda data: data.derived.hopper_fill_raw,
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

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:
        fn = self.entity_description.attributes_fn
        return fn(self.coordinator.data) if fn else None
