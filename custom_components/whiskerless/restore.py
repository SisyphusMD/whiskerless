"""Reading Home Assistant's restore cache on either side of Core 2026.11.

Core 2026.11 re-keyed the cache by entity registry id and replaced the
``last_states`` mapping with ``async_get_stored_state``. This integration
supports Core from before that change, so both shapes are read here and nowhere
else: a caller reaching into the cache directly fails the whole config entry on
whichever side it was not written for.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import restore_state


@callback
def stored_state(hass: HomeAssistant, entity_id: str | None) -> restore_state.StoredState | None:
    """What the restore cache holds for an entity, if anything."""
    if entity_id is None:
        return None
    # Any, because only one of the two attributes exists on whichever Core is
    # installed, and a typed access fails the strict check on the other.
    data: Any = restore_state.async_get(hass)
    lookup = getattr(data, "async_get_stored_state", None)
    stored: restore_state.StoredState | None = (
        lookup(entity_id) if lookup is not None else data.last_states.get(entity_id)
    )
    return stored


@callback
def move_stored_state(hass: HomeAssistant, old_entity_id: str, new_entity_id: str) -> None:
    """Carry an entity's cached state across a change of its entity_id.

    Only the older cache is keyed by entity_id. From Core 2026.11 it is keyed by
    registry id, which a rename leaves alone, so there is nothing to move.
    """
    cached = getattr(restore_state.async_get(hass), "last_states", None)
    if cached is not None and old_entity_id in cached:
        cached[new_entity_id] = cached.pop(old_entity_id)
