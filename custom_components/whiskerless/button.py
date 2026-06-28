"""Button platform for Whiskerless.

Only PROVEN-safe actions: the clean cycle (the single validated motor command)
and a manual state refresh. Power / empty / reset are deliberately absent — see
the docs for why they are not yet exposed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity, exception_handler

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class WhiskerlessButtonEntityDescription(ButtonEntityDescription):
    """Describes a Whiskerless button."""

    press_fn: Callable[[WhiskerlessCoordinator], Awaitable[None]]


BUTTONS: tuple[WhiskerlessButtonEntityDescription, ...] = (
    WhiskerlessButtonEntityDescription(
        key="start_clean_cycle",
        translation_key="start_clean_cycle",
        press_fn=lambda coordinator: coordinator.async_start_clean_cycle(),
    ),
    WhiskerlessButtonEntityDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        press_fn=lambda coordinator: coordinator.async_request_refresh(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless buttons."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessButton(coordinator, description) for description in BUTTONS)


class WhiskerlessButton(WhiskerlessEntity, ButtonEntity):
    """A Whiskerless button."""

    entity_description: WhiskerlessButtonEntityDescription

    def __init__(
        self,
        coordinator: WhiskerlessCoordinator,
        description: WhiskerlessButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @exception_handler
    @override
    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
