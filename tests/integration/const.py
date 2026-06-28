"""Shared constants for the integration tests."""

from __future__ import annotations

from custom_components.whiskerless.const import CONF_SERIAL
from homeassistant.const import CONF_NAME

MOCK_SERIAL = "LR4C000001"
MOCK_NAME = "Litter-Robot 4"
MOCK_CONFIG = {CONF_SERIAL: MOCK_SERIAL, CONF_NAME: MOCK_NAME}
STATE_TOPIC = f"prod/LR4/{MOCK_SERIAL}/state"
