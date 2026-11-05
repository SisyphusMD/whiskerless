"""Diagnostics support for Whiskerless."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL
from .coordinator import WhiskerlessConfigEntry
from .evo import is_evo_entry
from .evo.entity import evo_coordinator

TO_REDACT = {CONF_SERIAL, "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WhiskerlessConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    if is_evo_entry(entry):
        return _evo_diagnostics(entry)
    coordinator = entry.runtime_data
    robot = asdict(coordinator.data.robot)
    # The firmware's camelCase `raw` doc can carry identifiers that snake_case
    # redaction would miss, and it's redundant with the decoded fields — drop it.
    robot.pop("raw", None)
    derived = {
        key: value
        for key, value in asdict(coordinator.data).items()
        if key not in ("robot", "derived")
    }
    # The library's own serializer rather than asdict(): it renders the stamps
    # and the sighting enums as strings, which is what a diagnostics download is.
    derived.update(coordinator.data.derived.as_dict())
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


def _evo_diagnostics(entry: WhiskerlessConfigEntry) -> dict[str, Any]:
    """An EVO has no derived layer: the entry and what the robot has reported."""
    coordinator = evo_coordinator(entry)
    state = asdict(coordinator.data)
    # Every reported address, decoded or not, as hex — the part a protocol
    # question turns on, and JSON keys cannot be tuples.
    state["registers"] = {
        f"0x{bank:02X}{register:02X}": f"0x{value:04X}"
        for (bank, register), value in sorted(coordinator.data.registers.items())
    }
    state["sleep_days"] = sorted(coordinator.data.sleep_days)
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "available": coordinator.last_update_success,
            "state": state,
        },
        TO_REDACT,
    )
