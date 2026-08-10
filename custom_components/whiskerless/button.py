"""Button platform for Whiskerless.

Every action here is a synthesised panel button press on register `0x01`: the
write reproduces the exact code the panel emits, so the robot cannot tell it
from a finger. Clean cycle and reset are live-proven on ESP 1.1.75; empty and
power are captured from physical presses but have never been written, and both
ship disabled because their cost is high and their proof is thinner.

Both are immediate: Home Assistant has no entity-level confirmation prompt, so
being disabled by default is the only barrier an integration can put in front of
a destructive action.

The filter-change park is not here and cannot be: its chord is a long press, and
the firmware declines press type 02 on the write path.
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
        press_fn=lambda coordinator: coordinator.async_clean_cycle(),
    ),
    WhiskerlessButtonEntityDescription(
        key="panel_reset",
        translation_key="panel_reset",
        press_fn=lambda coordinator: coordinator.async_panel_reset(),
    ),
    # Disabled by default: it empties the globe. Recoverable (Cycle or Reset
    # brings it home) but it costs a litter refill, so it is opt-in.
    WhiskerlessButtonEntityDescription(
        key="start_empty_cycle",
        translation_key="start_empty_cycle",
        entity_registry_enabled_default=False,
        press_fn=lambda coordinator: coordinator.async_empty_cycle(),
    ),
    # Disabled by default, and the only entity whose failure mode is a walk to
    # the machine: Power toggles, and a robot switched off is off the network.
    WhiskerlessButtonEntityDescription(
        key="power_toggle",
        translation_key="power_toggle",
        entity_registry_enabled_default=False,
        press_fn=lambda coordinator: coordinator.async_power_toggle(),
    ),
    # Enabled: it is a read-only requestState publish, and it is what the
    # troubleshooting docs tell you to press when a robot has gone quiet — being
    # sent to enable an entity first is friction at exactly the wrong moment.
    WhiskerlessButtonEntityDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
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
