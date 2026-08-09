"""Constants for the Whiskerless integration."""

from __future__ import annotations

import logging
from datetime import timedelta

DOMAIN = "whiskerless"
LOGGER = logging.getLogger(__package__)

# The integration rides on Home Assistant's own MQTT integration, so a config
# entry stores only which robot it is and the name the user gave it at add time.
CONF_SERIAL = "serial"

# Per-robot litter calibration, captured by the calibration buttons and stored
# on the config entry options. CONF_LITTER_FULL_MM alone anchors the percentage
# the way the cloud does; adding CONF_LITTER_EMPTY_MM upgrades it to a true
# two-point scale with no assumed slope.
CONF_LITTER_FULL_MM = "litter_full_mm"
CONF_LITTER_EMPTY_MM = "litter_empty_mm"

# Default device name; the user can override it when adding a discovered robot,
# which sets the device name and therefore the generated entity_ids.
DEFAULT_NAME = "Litter-Robot 4"

# Heartbeat only — state arrives by push over MQTT. This bounds how long an
# unresponsive robot can still look available, and refreshes after writes.
HEARTBEAT_INTERVAL = timedelta(minutes=5)
