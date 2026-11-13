"""A robot's device is found the same way on either side of Core 2026.10.

The harness carries one Core release per leg, so the lookup the installed Core lacks is stood in
for here. The single-device lookup stops working in Core 2027.8, and the lookup replacing it does
not exist before 2026.10.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from custom_components.whiskerless import registry
from custom_components.whiskerless.const import DOMAIN
from homeassistant.core import HomeAssistant

ROBOT = SimpleNamespace(id="robot-device")


class _OneDevicePerIdentifier:
    """The registry before Core 2026.10: one device, and no list lookup."""

    def __init__(self, *devices: object) -> None:
        self.devices = devices

    def async_get_device(self, identifiers: set[tuple[str, str]]) -> object | None:
        return next((d for d in self.devices if (DOMAIN, "LR4C000001") in identifiers), None)


class _ManyDevicesPerIdentifier:
    """The registry from Core 2026.10: every match, and the single lookup deprecated."""

    def __init__(self, *devices: object) -> None:
        self.devices = devices

    def async_get_devices(self, *, identifiers: set[tuple[str, str]]) -> list[object]:
        assert identifiers == {(DOMAIN, "LR4C000001")}
        return list(self.devices)

    def async_get_device(self, **_: object) -> object:
        raise AssertionError("deprecated; stops working in Core 2027.8")


@pytest.mark.parametrize("shape", [_OneDevicePerIdentifier, _ManyDevicesPerIdentifier])
def test_the_robot_is_found_on_either_core(hass: HomeAssistant, shape: type) -> None:
    with patch.object(registry.dr, "async_get", lambda _hass: shape(ROBOT)):
        assert registry.robot_device(hass, "LR4C000001") is ROBOT
    with patch.object(registry.dr, "async_get", lambda _hass: shape()):
        assert registry.robot_device(hass, "LR4C000001") is None


def test_the_deprecated_lookup_is_used_in_one_place() -> None:
    """A second caller is a second thing that breaks in Core 2027.8."""
    package = Path(registry.__file__).parent
    elsewhere = sorted(
        path.name
        for path in package.rglob("*.py")
        if path.name != "registry.py" and re.search(r"\.async_get_device\(", path.read_text(encoding="utf-8"))
    )
    assert elsewhere == []
