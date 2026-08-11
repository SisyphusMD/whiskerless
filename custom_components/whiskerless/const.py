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
# Set once the hopper has reported. Durable, so the entities it enables stay
# enabled and the readings that proved it survive the reload enabling triggers.
CONF_HOPPER_SEEN = "hopper_seen"
CONF_HOPPER_LAST = "hopper_last"

# The same pair for the visit duration (register 0xBC), which is not optional
# hardware but an older-firmware gap: ESP 1.4.4 reports one at the end of every
# visit, and 1.1.75 never has. A 12h capture of a 1.1.75 robot logged five visits
# and three cat weights without a single duration, and on 1.4.4 a weight is always
# accompanied by one — so the sensor would sit unknown forever on that firmware.
CONF_VISIT_DURATION_SEEN = "visit_duration_seen"
CONF_VISIT_DURATION_LAST = "visit_duration_last"

# Extremes learned from what the robot reports, so a user who never calibrates
# still gets a scale. Explicit calibration overrides these.
CONF_LEARNED_LITTER = "learned_litter"
CONF_LEARNED_HOPPER = "learned_hopper"

CONF_LITTER_FULL_MM = "litter_full_mm"
CONF_LITTER_EMPTY_MM = "litter_empty_mm"

# Default device name; the user can override it when adding a discovered robot,
# which sets the device name and therefore the generated entity_ids.
DEFAULT_NAME = "Litter-Robot 4"

# Heartbeat only — state arrives by push over MQTT. This bounds how long an
# unresponsive robot can still look available, and refreshes after writes.
HEARTBEAT_INTERVAL = timedelta(minutes=5)
