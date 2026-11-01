"""Event platform for Whiskerless — moments, for automations and the notification blueprint.

Conditions (drawer full, a fault, offline) are binary sensors because they have an
end that an alert needs to clear on. A finished cycle has no end, so it is an event.
"""

from __future__ import annotations

from typing import override

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_4.derive import CleanCycleCompleted

from .const import SIGNAL_CLEAN_CYCLE
from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0

CLEAN_CYCLE = EventEntityDescription(
    key="clean_cycle",
    translation_key="clean_cycle",
    event_types=["completed"],
)

EVENTS: tuple[EventEntityDescription, ...] = (CLEAN_CYCLE,)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless event entities."""
    async_add_entities([WhiskerlessCleanCycleEvent(entry.runtime_data)])


class WhiskerlessCleanCycleEvent(WhiskerlessEntity, EventEntity):
    """Fires when a clean cycle this session watched start ends back at ready."""

    def __init__(self, coordinator: WhiskerlessCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_description = CLEAN_CYCLE
        self._attr_unique_id = f"{coordinator.serial}_{CLEAN_CYCLE.key}"

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CLEAN_CYCLE.format(self.coordinator.serial), self._completed
            )
        )

    @callback
    def _completed(self, effect: CleanCycleCompleted) -> None:
        self._trigger_event(
            "completed",
            {"cycle_count": effect.count, "waste_drawer_level": self._robot.waste_drawer_level},
        )
        self.async_write_ha_state()
