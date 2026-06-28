"""Litter-Robot 4 device metadata for the Whiskerless integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from whiskerless.devices.litter_robot_4 import LitterRobot4State

from ..const import DOMAIN

MANUFACTURER = "Whisker"
MODEL = "Litter-Robot 4"


def build_device_info(serial: str, name: str, robot: LitterRobot4State) -> DeviceInfo:
    """Build the device-registry entry for one robot.

    ``name`` is the user-chosen name from the discovery flow (default
    "Litter-Robot 4"); entity_ids are generated from it, and the serial is
    exposed separately as serial_number.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, serial)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=name,
        serial_number=serial,
        sw_version=robot.esp_firmware,
    )
