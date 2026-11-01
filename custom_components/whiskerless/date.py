"""Date platform for Whiskerless — when the user last did the maintenance the robot cannot see.

The notification blueprint reads these to say when a deep clean or a new filter is due.
They are records the user keeps, so they stay available if the robot goes offline. Setup
itself still waits for the robot's first answer, like every other entity here.
"""

from __future__ import annotations

from datetime import date
from typing import override

from homeassistant.components.date import DateEntity, DateEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator
from .entity import WhiskerlessEntity

PARALLEL_UPDATES = 0

DATES: tuple[DateEntityDescription, ...] = (
    DateEntityDescription(key="last_deep_clean", translation_key="last_deep_clean"),
    DateEntityDescription(key="last_filter_change", translation_key="last_filter_change"),
    DateEntityDescription(key="last_globe_clean", translation_key="last_globe_clean"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WhiskerlessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Whiskerless maintenance dates."""
    coordinator = entry.runtime_data
    async_add_entities(WhiskerlessMaintenanceDate(coordinator, d) for d in DATES)


class WhiskerlessMaintenanceDate(WhiskerlessEntity, DateEntity):
    """A maintenance date the user records; never read from or written to the robot."""

    def __init__(
        self, coordinator: WhiskerlessCoordinator, description: DateEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    @override
    def available(self) -> bool:
        return True

    @property
    @override
    def native_value(self) -> date | None:
        return self.coordinator.maintenance_date(self.entity_description.key)

    @override
    async def async_set_value(self, value: date) -> None:
        self.coordinator.async_set_maintenance_date(self.entity_description.key, value)
        self.async_write_ha_state()
