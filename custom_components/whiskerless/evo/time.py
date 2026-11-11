"""EVO time entities: the sleep and wake times.

The robot keeps a sleep and wake time per day. Each entity shows today's and
sets all seven days, matching the Litter-Robot 4's schedule entities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import time
from typing import Any, override

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from whiskerless.devices.litter_robot_evo import LitterRobotEvoState, const

from ..entity import exception_handler
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


def _today() -> str:
    # Python counts Monday as 0; the robot's week starts on Sunday.
    return const.WEEKDAYS[(dt_util.now().weekday() + 1) % 7]


@dataclass(frozen=True, kw_only=True)
class EvoTimeEntityDescription(TimeEntityDescription):
    """Describes an EVO time entity (minutes after midnight)."""

    value_fn: Callable[[LitterRobotEvoState], int | None]
    set_fn: Callable[[WhiskerlessEvoCoordinator, int], Awaitable[None]]


TIMES: tuple[EvoTimeEntityDescription, ...] = (
    EvoTimeEntityDescription(
        key="panel_sleep_time",
        translation_key="sleep_mode_start",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.sleep_times.get(_today()),
        set_fn=lambda coordinator, minutes: coordinator.async_set_sleep_time(minutes),
    ),
    EvoTimeEntityDescription(
        key="panel_wake_time",
        translation_key="sleep_mode_end",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda robot: robot.wake_times.get(_today()),
        set_fn=lambda coordinator, minutes: coordinator.async_set_wake_time(minutes),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO time entities."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoTime(coordinator, description) for description in TIMES)


class EvoTime(WhiskerlessEvoEntity, TimeEntity):
    """An EVO time entity."""

    entity_description: EvoTimeEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoTimeEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

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
