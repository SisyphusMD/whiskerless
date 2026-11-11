"""Litter-Robot EVO device metadata for the Whiskerless integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN

MANUFACTURER = "Whisker"
MODEL = "Litter-Robot EVO"


def build_device_info(serial: str, name: str) -> DeviceInfo:
    """Build the device-registry entry for one EVO.

    The EVO reports no firmware versions over MQTT, so unlike the Litter-Robot 4
    the entry carries no ``sw_version``.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=name,
        serial_number=serial,
    )
