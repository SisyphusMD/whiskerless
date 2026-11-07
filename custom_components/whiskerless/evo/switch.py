"""EVO switches: control panel lockout and sleep mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState

from ..entity import exception_handler
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoSwitchEntityDescription(SwitchEntityDescription):
    """Describes an EVO switch."""

    value_fn: Callable[[LitterRobotEvoState], bool | None]
    set_fn: Callable[[WhiskerlessEvoCoordinator, bool], Awaitable[None]]


def _sleep_on(robot: LitterRobotEvoState) -> bool | None:
    return None if robot.sleep_mask is None else robot.sleep_mask != 0


SWITCHES: tuple[EvoSwitchEntityDescription, ...] = (
    EvoSwitchEntityDescription(
        key="keypad_lockout",
        translation_key="keypad_lockout",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.keypad_lockout,
        set_fn=lambda coordinator, on: coordinator.async_set_keypad_lockout(on),
    ),
    # Sleep mode turns the cat sensor off between its start and end, so the robot
    # does not cycle automatically then. On arms it every day, as the Litter-Robot
    # 4's switch does; off disarms it. A schedule set to some days in the app reads
    # as on.
    EvoSwitchEntityDescription(
        key="weekday_sleep",
        translation_key="sleep_mode",
        entity_category=EntityCategory.CONFIG,
        value_fn=_sleep_on,
        set_fn=lambda coordinator, on: coordinator.async_set_sleep_enabled(on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO switches."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoSwitch(coordinator, description) for description in SWITCHES)


class EvoSwitch(WhiskerlessEvoEntity, SwitchEntity):
    """An EVO switch."""

    entity_description: EvoSwitchEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoSwitchEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._robot)

    @exception_handler
    @override
    async def async_turn_on(self, /, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, True)

    @exception_handler
    @override
    async def async_turn_off(self, /, **kwargs: Any) -> None:
        await self.entity_description.set_fn(self.coordinator, False)
