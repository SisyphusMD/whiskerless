"""EVO binary sensors: drawer, bonnet, power and cleaning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState

from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an EVO binary sensor."""

    value_fn: Callable[[LitterRobotEvoState], bool | None]


BINARY_SENSORS: tuple[EvoBinarySensorEntityDescription, ...] = (
    EvoBinarySensorEntityDescription(
        key="drawer_removed",
        translation_key="drawer_removed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda robot: robot.drawer_removed,
    ),
    EvoBinarySensorEntityDescription(
        key="bonnet_removed",
        translation_key="bonnet_removed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda robot: robot.bonnet_removed,
    ),
    EvoBinarySensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda robot: robot.power_on,
    ),
    EvoBinarySensorEntityDescription(
        key="cleaning",
        translation_key="cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda robot: robot.is_cleaning,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO binary sensors."""
    coordinator = evo_coordinator(entry)
    async_add_entities(
        EvoBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class EvoBinarySensor(WhiskerlessEvoEntity, BinarySensorEntity):
    """An EVO binary sensor."""

    entity_description: EvoBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessEvoCoordinator,
        description: EvoBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._robot)
