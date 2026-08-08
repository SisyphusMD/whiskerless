"""Litter-Robot 4 protocol constants — registers, opcodes, enums, topics.

Every value here is grounded in the reverse-engineering synthesis (see
``docs/devices/litter-robot-4/``). Confidence tags in comments mirror the
protocol bible: PROVEN (live-tested), HIGH (firmware-decisive), MED/LOW
(inference). The wire grammar and settings encodings are PROVEN; several enum
*integers* are only partially recovered, so decoders here tolerate both the raw
ints the firmware emits and the cloud-style strings, and fall back gracefully.
"""

from __future__ import annotations

from enum import IntEnum

# --- MQTT topics -------------------------------------------------------------
# The robot keeps the stock Whisker topic format after re-provisioning; only the
# broker it points at changes. SERIAL is the device serial / MQTT client-id.
TOPIC_PREFIX = "prod/LR4"


def command_topic(serial: str) -> str:
    """Topic the robot SUBSCRIBES to (we publish commands here)."""
    return f"{TOPIC_PREFIX}/{serial}/command"


def state_topic(serial: str) -> str:
    """Topic the robot PUBLISHES its full named state document to."""
    return f"{TOPIC_PREFIX}/{serial}/state"


def activity_topic(serial: str) -> str:
    """Topic the robot PUBLISHES telemetry / action echoes to."""
    return f"{TOPIC_PREFIX}/{serial}/activity"


def subscribe_topic(serial: str) -> str:
    """Wildcard covering state + activity (+ our own command echoes)."""
    return f"{TOPIC_PREFIX}/{serial}/#"


# --- ESP command opcodes (type-2 macro dispatch) -----------------------------
class Opcode(IntEnum):
    """The 9 ESP macro opcodes. Everything else is a generic register write."""

    REQUEST_STATE = 0xA0       # full named state doc → /state (READ-only)   PROVEN
    REPORT_SCHEDULE = 0xA1     # sleep/wake schedule + wifiRssi → /activity   PROVEN
    RESET_MB_OTA = 0xA3        # reset / main-board-OTA orchestrator — live: reboots or no-ops   NEVER
    GLOBE_MOTOR_OTA = 0xA4     # globe-motor OTA stager — BRICK RISK          NEVER
    REPORT_WIFI_EVENT = 0xA7   # wifi-event report → /activity (value 0 only) PROVEN
    REPORT_TOF = 0xA9          # ToF / sensor burst → /activity (READ-only)   PROVEN
    MB_FLASH = 0xAC            # main-board flash erase/write — BRICK         NEVER
    HW_RESET = 0xAD            # GPIO16 MCLR pulse + reg 0x30 — full PIC reboot NEVER
    REPORT_VERSION = 0xAE      # board id / firmware report → /activity       PROVEN


# Report macros that publish named JSON and are safe with value 0 (PROVEN live).
REPORT_MACROS: frozenset[int] = frozenset(
    {
        Opcode.REQUEST_STATE,
        Opcode.REPORT_SCHEDULE,
        Opcode.REPORT_WIFI_EVENT,
        Opcode.REPORT_TOF,
        Opcode.REPORT_VERSION,
    }
)


# --- PIC registers (flat namespace; type-1 read / type-2 write) --------------
class Register(IntEnum):
    """PIC register file. READ side is well-decoded; only the writable settings
    bank below is exposed for writes."""

    IS_DEBUG_MODE_ACTIVE = 0x05      # 64800-tick countdown when armed (not a bool)
    RTC_CHIP_ID = 0x06
    UNIT_POWER_TYPE = 0x07
    # Panel brightness, packed: hi-byte = DisplayIntensityHigh, lo-byte =
    # DisplayIntensityLow. High/Low name the AMBIENT light level, not the
    # brightness rank — behaviorally PROVEN on a live 1.4.4 robot with a
    # two-observation test: hi-byte forced to 5 → panel maximally dim in
    # daylight (hi = brightness in a BRIGHT room); at stock 40/50 in a
    # darkened room the panel stepped slightly BRIGHTER (lo = brightness in
    # a DARK room). Yes: the stock config is brighter at night (40/50).
    PANEL_BRIGHTNESS = 0x0E
    CAT_WEIGHT = 0x09                # activity: raw int16 / 100 = lb
    LITTER_HOPPER_DISPENSED = 0x0C   # activity
    CLEAN_CYCLE_WAIT_TIME = 0x16     # minutes (direct)
    IS_KEYPAD_LOCKOUT = 0x17         # 0/1
    NIGHT_LIGHT_MODE = 0x18          # 0=off 1=on 2=auto
    NIGHT_LIGHT_BRIGHTNESS = 0x19    # 0–100 % (direct, clamped)
    IS_PANEL_SLEEP_MODE = 0x1A       # 0/1
    PANEL_SLEEP_TIME = 0x1B          # minutes-since-midnight (16-bit)
    PANEL_WAKE_TIME = 0x1C           # minutes-since-midnight (16-bit)
    WEEKDAY_SLEEP_MODE_ENABLED = 0x1D  # 0/1
    # 0x1E–0x2B: per-weekday sleep/wake, see WEEKDAY_SCHEDULE_REGS
    UNIT_POWER_STATUS = 0x31
    SLEEP_STATUS = 0x32
    ROBOT_STATUS = 0x34
    GLOBE_MOTOR_FAULT_STATUS = 0x35
    CAT_DETECT = 0x37
    IS_USB_POWER_ON = 0x38
    USB_FAULT_STATUS = 0x39
    IS_BONNET_REMOVED = 0x3A
    IS_NIGHT_LIGHT_LED_ON = 0x3B
    ODOMETER_POWER_CYCLES = 0x3D
    ODOMETER_CLEAN_CYCLES = 0x3E
    ODOMETER_EMPTY_CYCLES = 0x3F
    ODOMETER_FILTER_CYCLES = 0x40
    IS_DFI_RESET_PENDING = 0x41      # read-only — NOT writable (0x02410001 is a no-op)
    DFI_NUMBER_OF_CYCLES = 0x42      # cycles since the firmware last DETECTED a
                                     # drawer empty. Not cleared by the empty itself
                                     # or by Reset; the firmware zeroes it (with
                                     # 0x45/0x46) on the first post-empty cycle whose
                                     # measurement confirms the drop — live-seen
                                     # twice, one and two cycles after a bag change
    # The drawer gauge is measurement-only on 1.4.4: it is read by three lasers
    # during the CYCLE_DFI phase (globe inverted) and NOT cleared by emptying
    # the drawer or pressing Reset — it self-corrects on the next cycle.
    # Percent tracks the primary raw laser (activity reg 0x48) at ≈ 0.70×raw
    # (r = 0.999 over a 38-cycle capture).
    DFI_LEVEL_PERCENT = 0x43         # waste drawer % (derived, see above)
    IS_DFI_FULL = 0x44
    DFI_FULL_COUNTER = 0x45
    DFI_TRIGGER_COUNT = 0x46
    LITTER_LEVEL = 0x47              # mm
    IS_DFI_PARTIAL_FULL = 0x4B       # one drawer SECTOR reads high while the rest
                                     # don't (three lasers = three sectors) — seen
                                     # live when a fresh bag liner bunched under
                                     # one laser: 21 % overall yet partial-full=1
    GLOBE_MOTOR_RETRACT_FAULT_STATUS = 0x4D
    ROBOT_CYCLE_STATUS = 0x4E
    ROBOT_CYCLE_STATE = 0x4F
    # Hopper link/state channel (activity only; not in the state document).
    # Live-observed on ESP 1.4.4 with a LitterHopper: 0xFFF1 (-15) = link lost
    # (fires on hopper detach AND bonnet lift — the hopper rides on the bonnet);
    # positive values (19/30/35-48/87) form an init/measurement sequence whose
    # exact meaning is still open. See docs/devices/litter-robot-4/registers.md.
    HOPPER_LINK = 0x57
    TOF1 = 0x58
    TOF2 = 0x59
    TOF3 = 0x5A
    # Waste-drawer bay events (activity only). Near-silent in continuous
    # capture except when the drawer moves. Two narrated pulls both emitted
    # 10 on removal; re-insert codes VARY (14, then 28 five days later), and
    # 12 fires occasionally with the drawer seated. Decode: 10 = removed,
    # anything else = seated.
    DRAWER_BAY = 0x56
    # Visit duration in seconds of settled weight on the scale (activity only;
    # fires once at visit end alongside the 0xB9 closure marker). Live-proven
    # against narrated visits: forced <5 s placements report 0, natural visits
    # 9-21 s. It also gates CAT_WEIGHT: ~9 s+ always produced a weight event,
    # 8 s and below often none. A Reset button press emits an unrelated large
    # value (592 observed) on the same register — see events.py's cap.
    CAT_VISIT_DURATION = 0xBC


# HOPPER_LINK (0x57) value meaning "hopper disconnected" (int16 -15, live-PROVEN
# on detach/reattach and bonnet lift/reseat).
HOPPER_LINK_DISCONNECTED = 0xFFF1

# DRAWER_BAY (0x56) removal code — consistent across both narrated pulls.
# (Re-insert codes vary — 14, 28 observed — so there is no INSERTED constant;
# any non-removal value means seated.)
DRAWER_BAY_REMOVED = 0x000A

# LITTER_HOPPER_DISPENSED (0x0C) phase whose value is the hopper's own fill
# gauge (see events.HopperDispensed).
HOPPER_DISPENSE_FILL_PHASE = 1

# Fill-gauge bands from a full live drain-to-refill arc (11 days, ESP 1.4.4):
# 89-92 maintained · 76→66 draining · 66-70 flatlined EMPTY (floor reading of
# the bare auger; the firmware itself never flags empty and keeps running a
# normal dispense every cycle) · 84 immediately after a refill (fresh litter
# mounds unevenly before dispenses redistribute it). The bands don't overlap;
# <= this threshold means empty.
HOPPER_FILL_EMPTY_MAX = 72


# Per-weekday sleep/wake registers (0x1E–0x2B). Sun→Sat, sleep-then-wake per day.
# ASSUMED layout (the round-trip is PROVEN; the exact day ordering is inferred —
# see docs/devices/litter-robot-4/compatibility.md before trusting day labels).
WEEKDAYS: tuple[str, ...] = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)
WEEKDAY_SCHEDULE_REGS: dict[str, tuple[int, int]] = {
    day: (0x1E + 2 * i, 0x1F + 2 * i) for i, day in enumerate(WEEKDAYS)
}


# --- Enums (firmware emits raw ints; decoders also accept cloud strings) ------
# robotStatus (0x34): only 4/10/13 are PROVEN; the rest are named for the cloud
# strings the device may emit but their integers are not yet pinned.
ROBOT_STATUS: dict[int, str] = {
    4: "ready",          # PROVEN
    10: "cat_detected",  # PROVEN (cat / weight pause)
    13: "clean_cycle",   # PROVEN (cycling)
}

# robotStatus on ESP >= 1.4: the firmware REMAPS the enum — most notably 10 now
# means "clean cycle in progress", NOT the 1.1.x cat/weight pause. Every value
# below was live-observed on an ESP 1.4.4 robot (labeled button session + 17
# natural cat visits / 15 auto cycles over 42 h of raw capture).
ROBOT_STATUS_ESP_1_4: dict[int, str] = {
    4: "ready",
    5: "bonnet_removed",
    6: "cat_sensor_timing",   # post-visit countdown, early tick
    7: "cat_sensor_timing",   # countdown / weight-hold (red panel light)
    10: "clean_cycle",        # != 1.1.x, where 10 is the cat/weight pause
    25: "cat_detected",       # weight on the scale / cat inside
}


def robot_status_map(esp_firmware: str | None) -> dict[int, str]:
    """Pick the robotStatus int map for the reporting firmware.

    ESP >= 1.4 remapped the enum (see :data:`ROBOT_STATUS_ESP_1_4`). Unknown or
    unparsable versions keep the legacy map, matching pre-1.4 behavior.
    """
    if esp_firmware:
        try:
            major, minor = (int(part) for part in esp_firmware.split(".")[:2])
        except ValueError:
            return ROBOT_STATUS
        if (major, minor) >= (1, 4):
            return ROBOT_STATUS_ESP_1_4
    return ROBOT_STATUS
ROBOT_STATUS_STRINGS: dict[str, str] = {
    "robot_idle": "ready",
    "robot_clean": "clean_cycle",
    "robot_find_dump": "clean_cycle",
    "robot_empty": "empty_cycle",
    "robot_cat_detect": "cat_detected",
    "robot_cat_detect_delay": "cat_sensor_timing",
    "robot_bonnet": "bonnet_removed",
    "robot_power_up": "powering_up",
    "robot_power_down": "powering_down",
    "robot_power_off": "off",
}
# Status values that mean the globe is actively cycling.
CLEANING_STATUSES: frozenset[str] = frozenset({"clean_cycle", "empty_cycle"})

NIGHT_LIGHT_MODE: dict[int, str] = {0: "off", 1: "on", 2: "auto"}  # PROVEN
# ESP 1.4.4 marches cycleStatus 2→3→4→5→1 per cycle (live-observed, 15/15).
# Phase names from the cloud's own strings, captured live during an
# app-triggered cycle on a cloud-connected 1.4.4 robot:
# CYCLE_DUMP → CYCLE_DFI → CYCLE_LEVEL → CYCLE_HOME → CYCLE_IDLE.
# NOTE: on 1.4.x, 3 = the DFI (drawer measurement) phase — the legacy "home"
# label for 3 does not match this firmware; 5 is the home/return phase (this
# is also when the LitterHopper dispenses: during CYCLE_LEVEL, value 4).
ROBOT_CYCLE_STATUS: dict[int, str] = {
    0: "init",
    1: "idle",
    2: "dump",
    3: "home",    # legacy label; on ESP >= 1.4 this phase is CYCLE_DFI
    4: "level",   # CYCLE_LEVEL (hopper dispenses here)
    5: "home",    # CYCLE_HOME
}
# ESP 1.4.4 also emits transient 12 (0x0C) / 15 (0x0F) states mid-cycle.
ROBOT_CYCLE_STATE: dict[int, str] = {
    1: "idle",
    2: "cycle",
    3: "cycle",
    # 4 = safety pause: a cat entered mid-cycle and the globe halted.
    # Owner-witnessed live (2026-07-31): cat jumped into a running cycle →
    # cat-detect burst + state 4, globe stopped; robotStatus stayed at
    # clean-cycle (10) throughout, so this state is the ONLY pause signal.
    # A Cycle press resumed, re-running the phase ladder from the top
    # without a second odometer tick. Every other capture of 4 (10/10)
    # coincided with cat-detect activity mid-cycle.
    4: "cat_interrupt",
    12: "cycle",  # ESP 1.4.x dump/return excursion
    15: "cycle",  # ESP 1.4.x dump/return excursion
}
# cycleStatus values that mean a cycle is actively running (used as a fallback
# is_cleaning signal when robotStatus is an unmapped int).
ACTIVE_CYCLE_STATUSES: frozenset[str] = frozenset({"dump", "home", "level", "cycle"})

# nightLightBrightness presets pylitterbot uses (the % is direct, these are labels).
BRIGHTNESS_PRESETS: dict[str, int] = {"low": 25, "medium": 50, "high": 100}

# clean-cycle wait-time minutes the app offers.
CLEAN_CYCLE_WAIT_MINUTES: tuple[int, ...] = (3, 7, 15, 25, 30)
