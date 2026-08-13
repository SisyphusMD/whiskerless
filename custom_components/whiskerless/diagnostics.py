"""Diagnostics support for Whiskerless."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL
from .coordinator import WhiskerlessConfigEntry

TO_REDACT = {CONF_SERIAL, "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WhiskerlessConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    robot = asdict(coordinator.data.robot)
    # The firmware's camelCase `raw` doc can carry identifiers that snake_case
    # redaction would miss, and it's redundant with the decoded fields — drop it.
    robot.pop("raw", None)
    derived = asdict(coordinator.data)
    derived.pop("robot", None)
    return async_redact_data(
        {
            "entry": dict(entry.data),
            # The options and derived facts are this integration's actual novel
            # state — learned scales, sighting flags, calibration — and they are
            # what support questions ("why is my hopper entity missing?") turn on.
            "options": dict(entry.options),
            "available": coordinator.last_update_success,
            "state": robot,
            "derived": derived,
        },
        TO_REDACT,
    )
