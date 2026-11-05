"""Shared constants for the integration tests."""

from __future__ import annotations

from custom_components.whiskerless.const import CONF_MODEL, CONF_SERIAL, MODEL_EVO
from homeassistant.const import CONF_NAME

MOCK_SERIAL = "LR4C000001"
MOCK_NAME = "Litter-Robot 4"
MOCK_CONFIG = {CONF_SERIAL: MOCK_SERIAL, CONF_NAME: MOCK_NAME}
STATE_TOPIC = f"prod/LR4/{MOCK_SERIAL}/state"
ACTIVITY_TOPIC = f"prod/LR4/{MOCK_SERIAL}/activity"

# A synthetic Litter-Robot EVO. Its topics use the prefix the driver provisions.
EVO_SERIAL = "LRE-01-40-01-2610-000000"
EVO_NAME = "Litter-Robot EVO"
EVO_CONFIG = {CONF_SERIAL: EVO_SERIAL, CONF_NAME: EVO_NAME, CONF_MODEL: MODEL_EVO}
EVO_ACTIVITY_TOPIC = f"prod/robots/{EVO_SERIAL}/activity"
EVO_EVENT_TOPIC = f"prod/robots/{EVO_SERIAL}/event"
EVO_COMMAND_TOPIC = f"prod/robots/{EVO_SERIAL}/command"
