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
    PANEL_BRIGHTNESS = 0x0E          # hi-byte = High, lo-byte = Low
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
    DFI_NUMBER_OF_CYCLES = 0x42
    DFI_LEVEL_PERCENT = 0x43         # waste drawer % (direct)
    IS_DFI_FULL = 0x44
    DFI_FULL_COUNTER = 0x45
    DFI_TRIGGER_COUNT = 0x46
    LITTER_LEVEL = 0x47              # mm
    IS_DFI_PARTIAL_FULL = 0x4B
    GLOBE_MOTOR_RETRACT_FAULT_STATUS = 0x4D
    ROBOT_CYCLE_STATUS = 0x4E
    ROBOT_CYCLE_STATE = 0x4F
    TOF1 = 0x58
    TOF2 = 0x59
    TOF3 = 0x5A


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
ROBOT_CYCLE_STATUS: dict[int, str] = {0: "init", 1: "idle", 2: "dump", 3: "home"}
ROBOT_CYCLE_STATE: dict[int, str] = {1: "idle", 2: "cycle", 3: "cycle", 4: "cycle"}

# nightLightBrightness presets pylitterbot uses (the % is direct, these are labels).
BRIGHTNESS_PRESETS: dict[str, int] = {"low": 25, "medium": 50, "high": 100}

# clean-cycle wait-time minutes the app offers.
CLEAN_CYCLE_WAIT_MINUTES: tuple[int, ...] = (3, 7, 15, 25, 30)
