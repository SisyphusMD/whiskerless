"""Finding a robot's device on either side of Core's device-registry change.

Core 2026.10 let device identifiers repeat across config entries and deprecated the single-device
lookup (it stops working in 2027.8), adding a lookup that returns every match. This integration
supports Core from before that, so both are read here and nowhere else.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


@callback
def robot_device(hass: HomeAssistant, serial: str) -> dr.DeviceEntry | None:
    """The device this integration registered for a robot's serial, if any.

    The identifier carries this integration's domain, so only this integration's own device can
    match it, and the first match is the robot's.
    """
    # Any, because only one of the two lookups exists on whichever Core is installed, and a typed
    # access fails the strict check on the other.
    registry: Any = dr.async_get(hass)
    identifiers = {(DOMAIN, serial)}
    if (find_all := getattr(registry, "async_get_devices", None)) is not None:
        found: list[dr.DeviceEntry] = find_all(identifiers=identifiers)
        return found[0] if found else None
    device: dr.DeviceEntry | None = registry.async_get_device(identifiers=identifiers)
    return device
