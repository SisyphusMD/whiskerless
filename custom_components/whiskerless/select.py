"""Select platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_4 import LitterRobot4State, const

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity, exception_handler

PARALLEL_UPDATES = 1

_NIGHT_LIGHT_MODE_INDEX = {name: value for value, name in const.NIGHT_LIGHT_MODE.items()}
_WAIT_OPTIONS = [str(minutes) for minutes in const.CLEAN_CYCLE_WAIT_MINUTES]


@dataclass(frozen=True, kw_only=True)
class WhiskerlessSelectEntityDescription(SelectEntityDescription):
    """Describes a Whiskerless select."""

    current_fn: Callable[[LitterRobot4State], str | None]
    select_fn: Callable[[WhiskerlessCoordinator, str], Awaitable[None]]


SELECTS: tuple[WhiskerlessSelectEntityDescription, ...] = (
    WhiskerlessSelectEntityDescription(
        key="night_light_mode",
        translation_key="night_light_mode",
        entity_category=EntityCategory.CONFIG,
        options=list(const.NIGHT_LIGHT_MODE.values()),
        current_fn=lambda robot: robot.night_light_mode,
        select_fn=lambda coordinator, option: coordinator.async_set_night_light_mode(
            _NIGHT_LIGHT_MODE_INDEX[option]
        ),
    ),
    WhiskerlessSelectEntityDescription(
        key="clean_cycle_wait",
        translation_key="clean_cycle_wait",
        entity_category=EntityCategory.CONFIG,
        options=_WAIT_OPTIONS,
        current_fn=lambda robot: (
            str(robot.clean_cycle_wait_minutes)
            if robot.clean_cycle_wait_minutes is not None
            else None
        ),
        select_fn=lambda coordinator, option: coordinator.async_set_clean_cycle_wait(int(option)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless selects."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessSelect(coordinator, description) for description in SELECTS)


class WhiskerlessSelect(WhiskerlessEntity, SelectEntity):
    """A Whiskerless select."""

    entity_description: WhiskerlessSelectEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def current_option(self) -> str | None:
        option = self.entity_description.current_fn(self._robot)
        options = self.entity_description.options
        return option if options is not None and option in options else None

    @exception_handler
    @override
    async def async_select_option(self, option: str) -> None:
        await self.entity_description.select_fn(self.coordinator, option)
