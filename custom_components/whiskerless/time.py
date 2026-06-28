"""Time platform for Whiskerless — the panel sleep/wake schedule."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import time
from typing import override

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_4 import LitterRobot4State

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity, exception_handler

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class WhiskerlessTimeEntityDescription(TimeEntityDescription):
    """Describes a Whiskerless time entity (minutes-since-midnight register)."""

    value_fn: Callable[[LitterRobot4State], int | None]
    set_fn: Callable[[WhiskerlessCoordinator, int], Awaitable[None]]


TIMES: tuple[WhiskerlessTimeEntityDescription, ...] = (
    WhiskerlessTimeEntityDescription(
        key="panel_sleep_time",
        translation_key="panel_sleep_time",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.panel_sleep_time,
        set_fn=lambda coordinator, minutes: coordinator.async_set_panel_sleep_time(minutes),
    ),
    WhiskerlessTimeEntityDescription(
        key="panel_wake_time",
        translation_key="panel_wake_time",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.panel_wake_time,
        set_fn=lambda coordinator, minutes: coordinator.async_set_panel_wake_time(minutes),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless time entities."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessTime(coordinator, description) for description in TIMES)


class WhiskerlessTime(WhiskerlessEntity, TimeEntity):
    """A Whiskerless time entity backed by a minutes-since-midnight register."""

    entity_description: WhiskerlessTimeEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessTimeEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def native_value(self) -> time | None:
        minutes = self.entity_description.value_fn(self._robot)
        if minutes is None or not 0 <= minutes < 1440:
            return None
        return time(hour=minutes // 60, minute=minutes % 60)

    @exception_handler
    @override
    async def async_set_value(self, value: time) -> None:
        await self.entity_description.set_fn(self.coordinator, value.hour * 60 + value.minute)
