"""Binary sensor platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from whiskerless.devices.litter_robot_4 import LitterRobot4State, derive

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WhiskerlessBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Whiskerless binary sensor."""

    value_fn: Callable[[LitterRobot4State], bool | None]


# Entities built by hand rather than from a description, so the retired-entity
# sweep in __init__ can still account for their keys. A key missing here gets its
# registry entry deleted and recreated on every reload, losing the user's entity
# ID, name, area and enabled state — test_retired_entities guards against that.
STANDALONE_KEYS: tuple[str, ...] = (
    "hopper_connected",
    "hopper_empty",
    "globe_motor_fault",
    "excess_weight",
)

BINARY_SENSORS: tuple[WhiskerlessBinarySensorEntityDescription, ...] = (
    WhiskerlessBinarySensorEntityDescription(
        key="cat_detected",
        translation_key="cat_detected",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        value_fn=lambda robot: robot.cat_detected,
    ),
    WhiskerlessBinarySensorEntityDescription(
        key="drawer_full",
        translation_key="drawer_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda robot: robot.is_dfi_full,
    ),
    WhiskerlessBinarySensorEntityDescription(
        key="bonnet_removed",
        translation_key="bonnet_removed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda robot: robot.is_bonnet_removed,
    ),
    # Was a switch. The firmware structurally refuses writes to 0x1A — it is
    # computed from the weekday schedule — so the switch was a control that
    # could only time out and error. The weekday switch and time entities are
    # the writable path; this reports the outcome.
    WhiskerlessBinarySensorEntityDescription(
        key="panel_sleep_mode",
        translation_key="panel_sleep_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda robot: robot.panel_sleep_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        WhiskerlessBinarySensor(coordinator, description) for description in BINARY_SENSORS
    ]
    entities.append(WhiskerlessHopperConnectedSensor(coordinator))
    entities.append(WhiskerlessHopperEmptySensor(coordinator))
    entities.append(WhiskerlessGlobeMotorFaultSensor(coordinator))
    entities.append(WhiskerlessExcessWeightSensor(coordinator))
    async_add_entities(entities)


class WhiskerlessBinarySensor(WhiskerlessEntity, BinarySensorEntity):
    """A Whiskerless binary sensor."""

    entity_description: WhiskerlessBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._robot)


class _RestoringBinarySensor(WhiskerlessEntity, BinarySensorEntity, RestoreEntity):
    """Base for verdicts that must survive a restart of Home Assistant.

    RestoreEntity is what puts an entity's last state in the restore cache at
    shutdown; the coordinator reads it back at setup and hands it to the
    derivation, so the rule for when a carried verdict expires lives with the
    rest of the protocol logic rather than in two entities.
    """


class WhiskerlessHopperConnectedSensor(WhiskerlessEntity, BinarySensorEntity):
    """LitterHopper presence, derived from dispense activity.

    It reports `on` once the robot has actually delivered litter and never
    reports `off`: there is no disconnect signal. `0x57` looked like one for
    months, but a narrated session produced positives with the hopper on the
    bench and `-15` for merely opening the hopper's drawer, with reattachment
    silent — so deriving connectivity from it turned a routine refill into a
    fault that never cleared. A missing hopper is indistinguishable from a
    well-fed one, because dispensing is demand-driven; unknown is the honest
    answer there.

    It needs no restore cache: the sighting that enables this entity is itself
    persisted, so a proven hopper comes back proven.
    """

    _attr_translation_key = "hopper_connected"
    _attr_entity_registry_enabled_default = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_hopper_connected"

    @property
    @override
    def is_on(self) -> bool | None:
        return self.coordinator.data.derived.hopper_connected


class WhiskerlessHopperEmptySensor(WhiskerlessEntity, BinarySensorEntity):
    """Hopper out of litter, judged against this unit's own learned floor.

    The firmware never flags empty — it keeps running a normal dispense every
    cycle, delivering nothing. The gauge gives it away: it flatlines at its
    floor across those futile dispenses. But floors differ per unit (61 vs
    66-70 across two robots, with stocked phase-1 readings as low as 58 seen),
    so a fixed threshold cries empty on a low-reading unit; the alert instead
    waits for this robot's floor to be confirmed across separate dispenses —
    the same standard the percentage sensor beside it holds itself to.

    Until the floor is learned it reports no-problem rather than unknown: with
    no floor there is no evidence of a problem, and the first genuine empty is
    itself what teaches the floor, so the alert comes alive a few flatlined
    dispenses into it and is exact from then on. No restore cache: the gauge
    and the learned floor are both persisted, so the verdict is re-derivable
    the moment the coordinator loads.
    """

    _attr_translation_key = "hopper_empty"
    _attr_entity_registry_enabled_default = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_hopper_empty"

    @property
    @override
    def is_on(self) -> bool | None:
        return bool(derive.hopper_empty(self.coordinator.data.derived))



class WhiskerlessGlobeMotorFaultSensor(_RestoringBinarySensor):
    """Globe-motor fault, from the activity stream OR the state document.

    It cannot read the state document alone. One robot raised a fault on the
    activity stream (`0x350001`, in messages whose envelope is `type: "fault"`),
    held it for 50 minutes, and cleared it — while `globeMotorFaultStatus` read 0
    in every one of the 1198 state documents it published across that capture,
    including six sampled during the fault itself. A sensor watching the field
    stayed `off` throughout a real fault.

    Either source raising a fault is a fault; the state field is kept because it
    is the only source on firmware that does populate it.

    It restores, because the activity stream only speaks on the edges. The
    observed fault lasted fifty minutes between its raise and its clear, and a
    reload inside that window would otherwise drop the latch and let the state
    field's cheerful 0 render an active fault as `off`.
    """

    _attr_translation_key = "globe_motor_fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_globe_motor_fault"

    @property
    @override
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return derive.globe_motor_faulted(data.derived, data.robot)


class WhiskerlessExcessWeightSensor(_RestoringBinarySensor):
    """Something has been sitting on the scale too long.

    The robot raises this itself and shows it on the panel as a blue bar with a
    partial yellow flash, but says nothing about it in the state document. Its
    own documentation defines the condition as the scale having read loaded for
    over 30 minutes, and catDetect bit 1 is that reading, so the condition is
    derivable even though the flag is not published.

    It matters because the robot will not cycle while it believes it is occupied.
    One unit here held bit 1 for 2 h 09 m after a bonnet was reseated slightly
    off, with its clean-cycle countdown stuck the whole time and no indication
    anywhere in Home Assistant. Pressing Reset zeroes the scale and clears it.

    It restores, because the run start is in memory only: a reload would
    otherwise restart a countdown that the robot has already been serving for
    hours, and each further reload would restart it again.

    Timing is deliberately coarse. Nothing schedules a callback at the threshold,
    so the sensor turns on at the next coordinator update, which is at worst one
    heartbeat (5 min) after the 30-minute mark. That is a bounded lateness on an
    advisory condition, against a timer that would need cancelling on every clear.
    """

    _attr_translation_key = "excess_weight"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_excess_weight"

    @property
    @override
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return derive.excess_weight(data.derived, data.robot, dt_util.utcnow())
