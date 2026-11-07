"""EVO numbers: the screen and status LED brightness, each on its own.

The Whisker app sets both levels together to one of three presets (Low 8,
Medium 20, High 40). The robot takes any pair from 1 to 100, so each level is
its own control here. 1 is the dimmest: the robot replaces 0 with 50.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_evo import LitterRobotEvoState, const

from ..entity import exception_handler
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoNumberEntityDescription(NumberEntityDescription):
    """Describes an EVO number."""

    value_fn: Callable[[LitterRobotEvoState], int | None]
    set_fn: Callable[[WhiskerlessEvoCoordinator, int], Awaitable[None]]


def _other_level(level: int | None) -> int:
    # Both levels travel in one write, so changing one needs the other. The robot
    # cannot be asked for it, and guessing would change it behind the user's back.
    if level is None:
        raise WhiskerlessError(
            "the robot has not reported its other brightness level yet; "
            "set the Panel brightness preset first"
        )
    return level


async def _set_screen(coordinator: WhiskerlessEvoCoordinator, value: int) -> None:
    led = _other_level(coordinator.data.led_brightness)
    await coordinator.async_set_panel_brightness(value, led)


async def _set_led(coordinator: WhiskerlessEvoCoordinator, value: int) -> None:
    screen = _other_level(coordinator.data.screen_brightness)
    await coordinator.async_set_panel_brightness(screen, value)


NUMBERS: tuple[EvoNumberEntityDescription, ...] = (
    EvoNumberEntityDescription(
        key="screen_brightness",
        translation_key="screen_brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=const.BRIGHTNESS_MIN,
        native_max_value=const.BRIGHTNESS_MAX,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda robot: robot.screen_brightness,
        set_fn=_set_screen,
    ),
    EvoNumberEntityDescription(
        key="status_led_brightness",
        translation_key="status_led_brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=const.BRIGHTNESS_MIN,
        native_max_value=const.BRIGHTNESS_MAX,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda robot: robot.led_brightness,
        set_fn=_set_led,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO numbers."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoNumber(coordinator, description) for description in NUMBERS)


class EvoNumber(WhiskerlessEvoEntity, NumberEntity):
    """An EVO number."""

    entity_description: EvoNumberEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoNumberEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self._robot)

    @exception_handler
    @override
    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, int(value))
