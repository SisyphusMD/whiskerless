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
# Set once the hopper has reported, and holds WHAT proved it (see the library's
# Evidence). Durable, so the entities it enables stay enabled and a later change
# to the standard of proof can re-examine only the sightings it disagrees with.
CONF_HOPPER_SEEN = "hopper_seen"
#: The last raw fill gauge, kept for good rather than dropped with the bootstrap
#: above. Dispensing is demand-driven, so a well-fed robot can go days without
#: one — long enough that a restart would otherwise leave the level unknown
#: until it next runs low.
CONF_HOPPER_FILL_RAW = "hopper_fill_raw"
#: Kept beside it: losing this on a restart would bring back an empty reading from
#: before a refill, and announce it as new.
CONF_HOPPER_GAUGE_STALE = "hopper_gauge_stale"

# The same pair for the visit duration (register 0xBC), which is not optional
# hardware but an older-firmware gap: ESP 1.4.4 reports one at the end of every
# visit, and 1.1.75 never has. A 12h capture of a 1.1.75 robot logged five visits
# and three cat weights without a single duration, and on 1.4.4 a weight is always
# accompanied by one — so the sensor would sit unknown forever on that firmware.
CONF_VISIT_DURATION_SEEN = "visit_duration_seen"

# Observation sensors gate on their first real report, the same pattern as the
# hopper: a sensor that exists before its fact has ever been emitted is a
# permanent unknown on a robot that never emits it (0x56 has never been seen on
# 1.1.75; one 1.1.75 robot has never emitted a weight). Controls are exempt —
# their existence is the capability, not a report.
CONF_DRAWER_SEEN = "drawer_seen"
CONF_PET_WEIGHT_SEEN = "pet_weight_seen"
CONF_CAT_VISIT_SEEN = "cat_visit_seen"

#: The whole derived state, snapshotted when a sighting is recorded so the
#: entities that sighting enables have a value the moment they appear — enabling
#: one reloads the entry, which builds a fresh coordinator. Dropped once that
#: reload has settled: kept longer it would be re-applied on every startup and
#: clobber the newer values the entities restore for themselves.
CONF_DERIVED = "derived"

# Extremes learned from what the robot reports, so a user who never calibrates
# still gets a scale. Explicit calibration overrides these.
CONF_LEARNED_LITTER = "learned_litter"
CONF_LEARNED_HOPPER = "learned_hopper"

CONF_LITTER_FULL_MM = "litter_full_mm"

# User-recorded maintenance dates, {key: ISO date}. Not derived from the robot,
# which has no way to know when someone deep-cleaned it.
CONF_MAINTENANCE = "maintenance"

# Dispatcher signal for a finished clean cycle, formatted with the serial.
SIGNAL_CLEAN_CYCLE = "whiskerless_clean_cycle_{}"
# Dispatcher signal for a finished cat visit, formatted with the serial.
SIGNAL_CAT_VISIT = "whiskerless_cat_visit_{}"

# Fired on Home Assistant's bus once per alert change; the notification blueprint
# and any automation listen for it. Documented in docs/setup/notifications.md.
EVENT_ALERT = "whiskerless_alert"
# Which condition alerts are active, so a restart does not announce them again.
CONF_ACTIVE_ALERTS = "active_alerts"
# Recent visit weights, the baseline for the weight-change alert.
CONF_WEIGHT_HISTORY = "weight_history"
# When the last visit ended, which the no-visit alert needs across a restart.
CONF_LAST_VISIT = "last_visit"
# The thresholds set in the integration's options.
CONF_ALERT_SETTINGS = "alert_settings"
# Per active alert: when it was raised, when last reminded, and which phones
# silenced it, so a restart neither re-times nor un-silences a reminder.
CONF_REMINDERS = "reminders"
# The Companion app event for a tapped notification button, and the prefix of the
# Silence button's action, which carries `<serial>|<alert>|<phone device id>`.
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
SILENCE_ACTION = "WHISKERLESS_SILENCE"
CONF_LITTER_EMPTY_MM = "litter_empty_mm"

# Default device name; the user can override it when adding a discovered robot,
# which sets the device name and therefore the generated entity_ids.
DEFAULT_NAME = "Litter-Robot 4"

# Heartbeat only — state arrives by push over MQTT. This bounds how long an
# unresponsive robot can still look available, and refreshes after writes.
HEARTBEAT_INTERVAL = timedelta(minutes=5)
