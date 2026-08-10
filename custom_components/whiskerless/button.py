"""Button platform for Whiskerless.

Clean cycle and reset work by synthesising a panel button press (register
`0x01`), live-proven on ESP 1.1.75. Empty and power are panel buttons too and
their codes are captured, but writing them is untested and both are costly to
get wrong: an empty cycle dumps every gram of litter into the drawer, and power
can take the robot off the network. The filter-change park is unreachable —
its chord is a long press, which the firmware declines on the write path.
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
    # Writes the code the robot itself emits when the panel Cycle button is
    # pressed. Motor-gated in the library; the coordinator opts in because a
    # person pressing this button is a deliberate act.
    WhiskerlessButtonEntityDescription(
        key="start_clean_cycle",
        translation_key="start_clean_cycle",
        press_fn=lambda coordinator: coordinator.async_clean_cycle(),
    ),
    WhiskerlessButtonEntityDescription(
        key="panel_reset",
        translation_key="panel_reset",
        press_fn=lambda coordinator: coordinator.async_panel_reset(),
    ),
    WhiskerlessButtonEntityDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        press_fn=lambda coordinator: coordinator.async_request_refresh(),
    ),
    # Litter percentage has no universal curve — the cloud measures against a
    # per-robot reference that is absent from the local state document. One
    # press with the globe filled to the line anchors it.
    WhiskerlessButtonEntityDescription(
        key="calibrate_litter_full",
        translation_key="calibrate_litter_full",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.async_calibrate_litter(empty=False),
    ),
    # Optional second point, but visible: an empty globe happens anyway after an
    # empty cycle or a litter change, and someone who has one in front of them
    # should not have to go and enable an entity first to use the moment.
    WhiskerlessButtonEntityDescription(
        key="calibrate_litter_empty",
        translation_key="calibrate_litter_empty",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.async_calibrate_litter(empty=True),
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
