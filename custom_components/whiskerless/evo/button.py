"""EVO buttons: the actions the Whisker app sends, and the empty cycle.

An empty cycle stops at the dump position until Cycle is pressed on the panel,
which sends the globe home. Power off stops the robot cleaning until it is
powered back on, so the driver classifies it dangerous; both power buttons are
enabled, since the robot stays connected while off and accepts Power on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ..entity import exception_handler
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator


@dataclass(frozen=True, kw_only=True)
class EvoButtonEntityDescription(ButtonEntityDescription):
    """Describes an EVO button."""

    press_fn: Callable[[WhiskerlessEvoCoordinator], Awaitable[None]]


BUTTONS: tuple[EvoButtonEntityDescription, ...] = (
    EvoButtonEntityDescription(
        key="start_clean_cycle",
        translation_key="start_clean_cycle",
        press_fn=lambda coordinator: coordinator.async_clean_cycle(),
    ),
    EvoButtonEntityDescription(
        key="start_empty_cycle",
        translation_key="evo_empty_cycle",
        press_fn=lambda coordinator: coordinator.async_empty_cycle(),
    ),
    EvoButtonEntityDescription(
        key="start_filter_change",
        translation_key="start_filter_change",
        press_fn=lambda coordinator: coordinator.async_change_filter(),
    ),
    EvoButtonEntityDescription(
        key="reset_drawer_level",
        translation_key="reset_drawer_level",
        press_fn=lambda coordinator: coordinator.async_reset_drawer_level(),
    ),
    EvoButtonEntityDescription(
        key="power_on",
        translation_key="power_on",
        press_fn=lambda coordinator: coordinator.async_power_on(),
    ),
    EvoButtonEntityDescription(
        key="power_off",
        translation_key="power_off",
        press_fn=lambda coordinator: coordinator.async_power_off(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up EVO buttons."""
    coordinator = evo_coordinator(entry)
    async_add_entities(EvoButton(coordinator, description) for description in BUTTONS)


class EvoButton(WhiskerlessEvoEntity, ButtonEntity):
    """An EVO button."""

    entity_description: EvoButtonEntityDescription

    def __init__(
        self, coordinator: WhiskerlessEvoCoordinator, description: EvoButtonEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @exception_handler
    @override
    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
