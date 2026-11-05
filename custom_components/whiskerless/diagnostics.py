"""Diagnostics support for Whiskerless."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .cloud_bridge import BridgeConfigEntry, is_bridge_entry
from .const import CONF_SERIAL
from .coordinator import WhiskerlessConfigEntry

TO_REDACT = {CONF_SERIAL, "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WhiskerlessConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    if is_bridge_entry(entry):
        return _bridge_diagnostics(cast(BridgeConfigEntry, entry))
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


def _bridge_diagnostics(entry: BridgeConfigEntry) -> dict[str, Any]:
    """A bridge's settings, state and recent traffic, without the serial or payloads.

    Payloads are left out: cloud messages can carry the account's pet profiles.
    """
    runtime = entry.runtime_data
    serial = runtime.serial

    def scrub(topic: str) -> str:
        return topic.replace(serial, "**REDACTED**")

    return async_redact_data(
        {
            "entry": dict(entry.data),
            "options": dict(entry.options),
            "state": runtime.state.value,
            "last_error": runtime.last_error and scrub(runtime.last_error),
            "recent_traffic": [
                {
                    "at": traffic.at.isoformat(),
                    "direction": traffic.direction.value,
                    "topic": scrub(traffic.topic),
                    "bytes": len(traffic.payload),
                    "injected": traffic.injected,
                }
                for traffic in runtime.recent
            ],
        },
        TO_REDACT,
    )
