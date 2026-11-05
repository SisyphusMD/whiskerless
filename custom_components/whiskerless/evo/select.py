"""EVO selects: the app's brightness presets plus Off, and cycle delays."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState, const

from ..entity import exception_handler
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoSelectEntityDescription(SelectEntityDescription):
    """Describes an EVO select."""

    value_fn: Callable[[LitterRobotEvoState], str | None]
    select_fn: Callable[[WhiskerlessEvoCoordinator, str], Awaitable[None]]


#: The app's presets, plus Off: both levels at 1, the dimmest the robot shows
#: (it turns 0 into 50).
_PRESETS: dict[str, int] = {"off": 1, **const.BRIGHTNESS_PRESETS}


def _preset(robot: LitterRobotEvoState) -> str | None:
    """The preset both levels match, or None for a custom pair."""
    if robot.screen_brightness is None or robot.screen_brightness != robot.led_brightness:
        return None
    return next(
        (name for name, level in _PRESETS.items() if level == robot.screen_brightness),
        None,
    )


async def _set_preset(coordinator: WhiskerlessEvoCoordinator, option: str) -> None:
    level = _PRESETS[option]
    await coordinator.async_set_panel_brightness(level, level)


def _cycle_delay(robot: LitterRobotEvoState) -> str | None:
    minutes = robot.cycle_delay_minutes
    return str(minutes) if minutes in const.CYCLE_DELAY_CHOICES else None


SELECTS: tuple[EvoSelectEntityDescription, ...] = (
    EvoSelectEntityDescription(
        key="panel_brightness_preset",
        translation_key="panel_brightness_preset",
        entity_category=EntityCategory.CONFIG,
        options=list(_PRESETS),
        value_fn=_preset,
        select_fn=_set_preset,
    ),
    # A select, not a number: these are the values the app offers, and the only
    # ones the robot is known to accept.
    EvoSelectEntityDescription(
        key="cycle_delay",
        translation_key="cycle_delay",
        entity_category=EntityCategory.CONFIG,
        options=[str(minutes) for minutes in const.CYCLE_DELAY_CHOICES],
        value_fn=_cycle_delay,
        select_fn=lambda coordinator, option: coordinator.async_set_cycle_delay(int(option)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO selects."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoSelect(coordinator, description) for description in SELECTS)


class EvoSelect(WhiskerlessEvoEntity, SelectEntity):
    """An EVO select."""

    entity_description: EvoSelectEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoSelectEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self._robot)

    @exception_handler
    @override
    async def async_select_option(self, option: str) -> None:
        await self.entity_description.select_fn(self.coordinator, option)
