"""Base entity for a Litter-Robot EVO."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState

from ..devices.litter_robot_evo import build_device_info
from .coordinator import WhiskerlessEvoCoordinator


def evo_coordinator(entry: ConfigEntry[Any]) -> WhiskerlessEvoCoordinator:
    """The coordinator of an EVO entry."""
    return cast(WhiskerlessEvoCoordinator, entry.runtime_data)


class WhiskerlessEvoEntity(CoordinatorEntity[WhiskerlessEvoCoordinator]):
    """Base EVO entity, keyed ``{serial}_{key}`` like the Litter-Robot 4's."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WhiskerlessEvoCoordinator, key: str) -> None:
        """Initialize the entity and build its device info once."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_{key}"
        self._attr_device_info = build_device_info(coordinator.serial, coordinator.device_name)

    @property
    def _robot(self) -> LitterRobotEvoState:
        """The current robot snapshot."""
        return self.coordinator.data
