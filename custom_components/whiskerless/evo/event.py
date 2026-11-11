"""EVO event entity: the records the robot publishes on its event topic.

``cycle`` arrives when a cycle completes and ``usage`` for a weight event, which
includes the drawer being reseated as well as a cat; a usage record carries the
weight in pounds. The record's elements are passed on as published, since most of
their registers are not decoded yet. ``pet_id_match`` fires when the robot matches
a weight to one of the account's pet profiles.
"""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless.devices.litter_robot_evo import EventMessage, PawprintMessage, const

from ..const import SIGNAL_EVO_EVENT
from .coordinator import WhiskerlessEvoCoordinator
from .entity import WhiskerlessEvoEntity, evo_coordinator

PARALLEL_UPDATES = 0

ROBOT_EVENT = EventEntityDescription(
    key="robot_event",
    translation_key="robot_event",
    event_types=["cycle", "usage", "pet_id_match"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[Any],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EVO event entity."""
    async_add_entities([EvoRobotEvent(evo_coordinator(entry))])


class EvoRobotEvent(WhiskerlessEvoEntity, EventEntity):
    """Fires for each ``cycle`` or ``usage`` record and each pet the robot identifies."""

    def __init__(self, coordinator: WhiskerlessEvoCoordinator) -> None:
        super().__init__(coordinator, ROBOT_EVENT.key)
        self.entity_description = ROBOT_EVENT

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_EVO_EVENT.format(self.coordinator.serial), self._recorded
            )
        )

    @callback
    def _recorded(self, record: EventMessage | PawprintMessage) -> None:
        if isinstance(record, PawprintMessage):
            match = record.pet_id_match
            if match is None:
                return
            self._trigger_event(
                "pet_id_match",
                {
                    "profile": match.profile,
                    "confidence": match.confidence,
                    "sources": list(match.sources),
                },
            )
            self.async_write_ha_state()
            return
        if record.event_type not in self.event_types:
            return
        attributes: dict[str, Any] = {
            "uuid": record.uuid,
            "data": [reading.hex for reading in record.readings],
        }
        for reading in record.readings:
            if (reading.bank, reading.register) == (const.Bank.USAGE, const.UsageRegister.WEIGHT):
                attributes["weight_lb"] = reading.value / 100
        self._trigger_event(record.event_type, attributes)
        self.async_write_ha_state()
