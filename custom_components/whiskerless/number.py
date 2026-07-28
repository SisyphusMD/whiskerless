"""Number platform for Whiskerless."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_4 import LitterRobot4State

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity, exception_handler

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class WhiskerlessNumberEntityDescription(NumberEntityDescription):
    """Describes a Whiskerless number."""

    value_fn: Callable[[LitterRobot4State], float | None]
    set_fn: Callable[[WhiskerlessCoordinator, int], Awaitable[None]]


async def _set_panel_high(coordinator: WhiskerlessCoordinator, value: int) -> None:
    low = coordinator.data.robot.display_intensity_low
    if low is None:
        raise WhiskerlessError("panel brightness not yet reported; refresh first")
    await coordinator.async_set_panel_brightness(value, low)


async def _set_panel_low(coordinator: WhiskerlessCoordinator, value: int) -> None:
    high = coordinator.data.robot.display_intensity_high
    if high is None:
        raise WhiskerlessError("panel brightness not yet reported; refresh first")
    await coordinator.async_set_panel_brightness(high, value)


NUMBERS: tuple[WhiskerlessNumberEntityDescription, ...] = (
    WhiskerlessNumberEntityDescription(
        key="night_light_brightness",
        translation_key="night_light_brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda robot: robot.night_light_brightness,
        set_fn=lambda coordinator, value: coordinator.async_set_night_light_brightness(value),
    ),
    WhiskerlessNumberEntityDescription(
        key="panel_brightness_high",
        translation_key="panel_brightness_high",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda robot: robot.display_intensity_high,
        set_fn=_set_panel_high,
    ),
    WhiskerlessNumberEntityDescription(
        key="panel_brightness_low",
        translation_key="panel_brightness_low",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda robot: robot.display_intensity_low,
        set_fn=_set_panel_low,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless numbers."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessNumber(coordinator, description) for description in NUMBERS)


class WhiskerlessNumber(WhiskerlessEntity, NumberEntity):
    """A Whiskerless number."""

    entity_description: WhiskerlessNumberEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self._robot)

    @exception_handler
    @override
    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, int(value))
