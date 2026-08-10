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
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from whiskerless.devices.litter_robot_4 import LitterRobot4State
from whiskerless.devices.litter_robot_4 import const as lr4

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WhiskerlessBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Whiskerless binary sensor."""

    value_fn: Callable[[LitterRobot4State], bool | None]


def _globe_fault(robot: LitterRobot4State) -> bool | None:
    if robot.globe_motor_fault is None:
        return None
    return robot.globe_motor_fault != 0


# Entities built by hand rather than from a description, so the retired-entity
# sweep in __init__ can still account for their keys. A key missing here gets its
# registry entry deleted and recreated on every reload, losing the user's entity
# ID, name, area and enabled state — test_retired_entities guards against that.
STANDALONE_KEYS: tuple[str, ...] = (
    "hopper_connected",
    "hopper_empty",
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
    WhiskerlessBinarySensorEntityDescription(
        key="globe_motor_fault",
        translation_key="globe_motor_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_globe_fault,
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
    """Base for sensors whose only source is an activity event.

    The robot speaks these registers on an event and never in the state
    document, so a restart would otherwise blank them until the next drawer
    pull, visit or dispense — potentially days for the drawer.
    """

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self._restored: bool | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._restored = last.state == STATE_ON

    def _with_restore(self, current: bool | None) -> bool | None:
        return self._restored if current is None else current


class WhiskerlessHopperConnectedSensor(_RestoringBinarySensor):
    """LitterHopper link state, derived from the activity stream (reg 0x57).

    The state document carries no hopper fields locally; the link register is
    the only signal. Unknown until the hopper first speaks (visit or dispense).
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
        data = self.coordinator.data
        if data.hopper_link_reported:
            # 0x57 deliberately reports None for a fault we cannot name; a
            # restored value must not dress that up as connected.
            return data.hopper_connected
        return self._restored


class WhiskerlessHopperEmptySensor(_RestoringBinarySensor):
    """Hopper out of litter, from the fill gauge (dispense phase 1).

    The firmware never flags empty — it keeps running a normal dispense every
    cycle, delivering nothing. The gauge gives it away: it flatlines at its
    66-70 floor when empty vs 76+ whenever litter is present (live-proven
    across a full drain-to-refill arc). Unknown until the first dispense.
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
        raw = self.coordinator.data.hopper_fill_raw
        if raw is None:
            return self._restored
        return raw <= lr4.HOPPER_FILL_EMPTY_MAX

