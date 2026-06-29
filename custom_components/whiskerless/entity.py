"""Base entity for the Whiskerless integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Concatenate

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_4 import LitterRobot4State

from .const import DOMAIN
from .coordinator import WhiskerlessCoordinator
from .devices.litter_robot_4 import build_device_info


class WhiskerlessEntity(CoordinatorEntity[WhiskerlessCoordinator]):
    """Base Whiskerless entity. Availability is inherited from CoordinatorEntity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        """Initialize the entity and build its device info once."""
        super().__init__(coordinator)
        self._attr_device_info = build_device_info(
            coordinator.serial, coordinator.device_name, coordinator.data.robot
        )

    @property
    def _robot(self) -> LitterRobot4State:
        """The current robot snapshot."""
        return self.coordinator.data.robot


def exception_handler[EntityT: WhiskerlessEntity, **P](
    func: Callable[Concatenate[EntityT, P], Coroutine[Any, Any, Any]],
) -> Callable[Concatenate[EntityT, P], Coroutine[Any, Any, None]]:
    """Translate a lib error from a command method into a HomeAssistantError."""

    async def handler(self: EntityT, /, *args: P.args, **kwargs: P.kwargs) -> None:
        try:
            await func(self, *args, **kwargs)
        except WhiskerlessError as error:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(error)},
            ) from error

    return handler
