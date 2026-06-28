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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_4 import LitterRobot4State

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
    async_add_entities(
        WhiskerlessBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


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
