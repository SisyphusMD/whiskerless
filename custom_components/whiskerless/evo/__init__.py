"""Litter-Robot EVO support for the Whiskerless integration.

An EVO entry gets its own coordinator and entities. The top-level platform
modules hand an EVO entry to the matching module here, so none of the
Litter-Robot 4's state derivation, calibration or alerts runs for it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from ..const import CONF_MODEL, MODEL_EVO
from .coordinator import WhiskerlessEvoCoordinator

EVO_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


def is_evo_entry(entry: ConfigEntry[Any]) -> bool:
    """Whether ``entry`` is a Litter-Robot EVO."""
    return entry.data.get(CONF_MODEL) == MODEL_EVO


async def async_setup_evo_entry(hass: HomeAssistant, entry: ConfigEntry[Any]) -> bool:
    """Set up one EVO: subscribe, then add its entities."""
    coordinator = WhiskerlessEvoCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, EVO_PLATFORMS)
    return True
