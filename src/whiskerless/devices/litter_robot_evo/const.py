"""Litter-Robot EVO protocol constants — banks, registers, enums, topics.

Every value here is grounded in ``docs/devices/litter-robot-evo/protocol.md``.
Confidence tags in comments mirror that reference: PROVEN (the robot echoed the
write, or the value matched the field Whisker's cloud reported at the same
moment), INFERRED (fits every observation), OPEN (seen, not understood).

The EVO addresses everything by bank and register. Commands are
``0xTTBBRRVVVV`` and telemetry is ``0xBBRRVVVV``; see :mod:`.codec`.
"""

from __future__ import annotations

from enum import IntEnum

"""Every constant this module promises. Same contract as `commands.__all__`."""
__all__ = [
    "BRIGHTNESS_MAX",
    "BRIGHTNESS_MIN",
    "BRIGHTNESS_PRESETS",
    "BRIGHTNESS_ZERO_SUBSTITUTE",
    "BUTTON_CANCEL",
    "BUTTON_CANCEL_HOLD",
    "BUTTON_CONNECT",
    "BUTTON_CYCLE",
    "BUTTON_CYCLE_HOLD",
    "CYCLE_DELAY_CHOICES",
    "DISPLAY_CODES",
    "READABLE_REGISTERS",
    "ROBOT_STATUS",
    "SLEEP_ALL_DAYS",
    "SLEEP_SCHEDULE_REGS",
    "TOPIC_PREFIX",
    "WEEKDAYS",
    "Bank",
    "BoardRegister",
    "MeasureRegister",
    "RobotCommand",
    "RobotRegister",
    "SensorRegister",
    "SettingsRegister",
    "UsageRegister",
    "activity_topic",
    "command_topic",
    "event_topic",
    "subscribe_topic",
]

# --- MQTT topics -------------------------------------------------------------
# The Whisker app provisions `prod/robots/<serial>/command` (subscribe) and
# `prod/robots/<serial>/activity` (publish); the robot derives its other topics
# (`event`) from the publish endpoint's prefix. A robot provisioned with a
# different prefix uses that one instead, so every helper takes it as a keyword.
TOPIC_PREFIX = "prod/robots"


def command_topic(serial: str, *, prefix: str = TOPIC_PREFIX) -> str:
    """Topic the robot SUBSCRIBES to (we publish commands here)."""
    return f"{prefix}/{serial}/command"


def activity_topic(serial: str, *, prefix: str = TOPIC_PREFIX) -> str:
    """Topic the robot PUBLISHES telemetry, write echoes and read replies to."""
    return f"{prefix}/{serial}/activity"


def event_topic(serial: str, *, prefix: str = TOPIC_PREFIX) -> str:
    """Topic the robot PUBLISHES cycle and usage records to."""
    return f"{prefix}/{serial}/event"


def subscribe_topic(serial: str, *, prefix: str = TOPIC_PREFIX) -> str:
    """Wildcard covering activity + event (+ command echoes, which are ignored)."""
    return f"{prefix}/{serial}/#"


# --- address space -----------------------------------------------------------
class Bank(IntEnum):
    """The first address byte."""

    ROBOT = 0x01     # actions, status, panel, hardware state         PROVEN
    SETTINGS = 0x02  # user settings, written by the app              PROVEN
    USAGE = 0x03     # weight-event elements on the event topic       PROVEN
    SENSORS = 0x05   # weight, drawer counters, motor readings        INFERRED
    MEASURE = 0x08   # measurement flags                              INFERRED
    BOARD = 0x09     # main-board identity and motor data             INFERRED


class RobotRegister(IntEnum):
    """Bank 01."""

    BUTTON = 0x01              # panel press: see BUTTON_CYCLE and siblings      PROVEN
    DISPLAY_CODE = 0x02        # what the panel shows, see DISPLAY_CODES        PROVEN
    ROBOT_STATUS = 0x03        # see ROBOT_STATUS; writable to start an action  PROVEN
    POWER_CYCLES = 0x05        # power-cycle odometer, reported at power-on     PROVEN
    EMPTY_CYCLES = 0x07        # empty-cycle odometer                           PROVEN
    CYCLE_STEP = 0x0A          # 1-5 clean, 6 empty, 7 empty return, 0x0E/0x0F filter INFERRED
    CYCLE_PHASE = 0x0B         # marker around each cycle step                  INFERRED
    POWER = 0x14               # 1 on, 0 off                                    PROVEN
    BONNET_REMOVED = 0x18      # 1/0                                            PROVEN
    DRAWER_REMOVED = 0x20      # 1/0                                            PROVEN
    DRAWER_LEVEL_RESET = 0x22  # write 1 to zero the drawer counters            PROVEN


class SettingsRegister(IntEnum):
    """Bank 02. Every write is echoed on activity with the value applied."""

    PANEL_BRIGHTNESS = 0x01  # high byte screen, low byte status LED, 1-100   PROVEN
    # 0x02-0x08: the robot's clock in local time, see CLOCK_REGS
    CLOCK_WEEKDAY = 0x02     # 0 = Sunday                                     INFERRED base
    CLOCK_HOUR = 0x03        # 0-23                                           PROVEN
    CLOCK_MINUTE = 0x04      # 0-59                                           PROVEN
    CLOCK_SECOND = 0x05      # 0-59                                           PROVEN
    CLOCK_DAY = 0x06         # day of the month, 1-31                         PROVEN
    CLOCK_MONTH = 0x07       # 1-12                                           PROVEN
    CLOCK_YEAR = 0x08        # two digits: 26 = 2026                          PROVEN
    CYCLE_DELAY = 0x09       # minutes                                        PROVEN
    KEYPAD_LOCKOUT = 0x0A    # 0/1                                            PROVEN
    SLEEP_DAYS = 0x10        # bitmask, bit 0 = Sunday                        PROVEN
    # 0x11-0x1E: sleep/wake minutes per day, see SLEEP_SCHEDULE_REGS


class UsageRegister(IntEnum):
    """Bank 03: elements of `usage` event records."""

    WEIGHT = 0x06  # weight in hundredths of a pound                     PROVEN


class SensorRegister(IntEnum):
    """Bank 05."""

    DRAWER_COUNTER = 0x0A  # drawer fullness; zeroed by the drawer reset      INFERRED
    WEIGHT = 0x1B          # signed 16-bit; scale OPEN                        INFERRED


class MeasureRegister(IntEnum):
    """Bank 08."""

    WEIGHT_SETTLING = 0x12  # 1 while a weight measurement settles, then 0   INFERRED


class BoardRegister(IntEnum):
    """Bank 09."""

    MAIN_BOARD_ID = 0x08  # reads 0x2904, the board id in the robot firmware string INFERRED


class RobotCommand(IntEnum):
    """Values written to bank 01 register 03 to start an action."""

    CLEAN_CYCLE = 0x0A    # robot reports status 0x0A                         PROVEN
    EMPTY_CYCLE = 0x0B    # robot reports status 0x0B                         PROVEN
    CHANGE_FILTER = 0x0C  # robot reports status 0x0E                         PROVEN


# --- reads -------------------------------------------------------------------
#: Addresses whose read reply carries the register's current value.   PROVEN
#: Every other address answers a read with 0 whatever it holds (the display
#: code, the weight sensor, the drawer counters, the motor readings and the
#: usage elements among them), so a read of one of those reports nothing.
READABLE_REGISTERS: frozenset[tuple[int, int]] = frozenset(
    {
        (Bank.ROBOT, RobotRegister.ROBOT_STATUS),
        (Bank.ROBOT, RobotRegister.POWER_CYCLES),
        (Bank.ROBOT, 0x06),
        (Bank.ROBOT, RobotRegister.EMPTY_CYCLES),
        (Bank.ROBOT, 0x08),
        (Bank.ROBOT, RobotRegister.CYCLE_STEP),
        (Bank.ROBOT, RobotRegister.CYCLE_PHASE),
        (Bank.ROBOT, RobotRegister.POWER),
        (Bank.ROBOT, RobotRegister.BONNET_REMOVED),
        (Bank.ROBOT, RobotRegister.DRAWER_REMOVED),
        (Bank.ROBOT, RobotRegister.DRAWER_LEVEL_RESET),
        (Bank.SETTINGS, SettingsRegister.PANEL_BRIGHTNESS),
        (Bank.SETTINGS, SettingsRegister.CYCLE_DELAY),
        (Bank.SETTINGS, SettingsRegister.KEYPAD_LOCKOUT),
        (Bank.SETTINGS, SettingsRegister.SLEEP_DAYS),
        *((Bank.SETTINGS, register) for register in range(0x11, 0x1F)),
        (Bank.SENSORS, 0x14),
        (Bank.BOARD, BoardRegister.MAIN_BOARD_ID),
        # Meaning unknown; each answers a read with a non-zero value.     OPEN
        (Bank.ROBOT, 0x16),
        (Bank.SETTINGS, 0x0F),
        (0x06, 0x0A),
    }
)

#: The clock registers, in the order the cloud writes them. The sleep schedule
#: runs on this clock.
CLOCK_REGS: tuple[int, ...] = (
    SettingsRegister.CLOCK_WEEKDAY,
    SettingsRegister.CLOCK_HOUR,
    SettingsRegister.CLOCK_MINUTE,
    SettingsRegister.CLOCK_SECOND,
    SettingsRegister.CLOCK_DAY,
    SettingsRegister.CLOCK_MONTH,
    SettingsRegister.CLOCK_YEAR,
)

# --- panel -------------------------------------------------------------------
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 100
#: The robot replaces a level of 0 with this one, so 0 is never sent.  PROVEN
BRIGHTNESS_ZERO_SUBSTITUTE = 50
#: The app's presets write both levels equal.                          PROVEN
BRIGHTNESS_PRESETS: dict[str, int] = {"low": 8, "medium": 20, "high": 40}

#: Values the robot reports in register 01/01: the high byte is the button (02
#: Cycle, 04 Cancel, 08 Connect), the low byte the press (01 short, 02 held for
#: about 3 seconds). Writes to this register are untested; actions start through
#: ROBOT_STATUS instead.
#: Cycle: starts a clean cycle, resumes a paused cycle, and sends a paused empty
#: cycle home.                                                        PROVEN
BUTTON_CYCLE = 0x0201
#: Cycle held: starts an empty cycle.                                  PROVEN
BUTTON_CYCLE_HOLD = 0x0202
#: Cancel: zeroes the weight sensors at home, dismisses resettable alerts. PROVEN
BUTTON_CANCEL = 0x0401
#: Cancel held: starts the filter-change rotation.                     INFERRED
BUTTON_CANCEL_HOLD = 0x0402
#: Connect: confirms the filter-change step.                           PROVEN
BUTTON_CONNECT = 0x0801

# --- cycle delay -------------------------------------------------------------
#: The values the app offers. The register takes minutes directly.
CYCLE_DELAY_CHOICES: tuple[int, ...] = (3, 7, 15)

# --- sleep schedule ----------------------------------------------------------
WEEKDAYS: tuple[str, ...] = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)
#: (sleep register, wake register) per day, Sunday first, minutes after midnight.
SLEEP_SCHEDULE_REGS: dict[str, tuple[int, int]] = {
    day: (0x11 + 2 * i, 0x12 + 2 * i) for i, day in enumerate(WEEKDAYS)
}
SLEEP_ALL_DAYS = 0x7F

# --- enums -------------------------------------------------------------------
#: Bank 01 register 03.
ROBOT_STATUS: dict[int, str] = {
    0x02: "powering_up",       # PROVEN
    0x03: "powering_down",     # PROVEN
    0x04: "ready",             # PROVEN
    0x0A: "cleaning",          # PROVEN
    0x0B: "emptying",          # PROVEN
    0x0E: "changing_filter",   # PROVEN
}

#: Bank 01 register 02, named after the cloud's `displayCode` where it has one.
DISPLAY_CODES: dict[int, str] = {
    0x06: "drawer_removed",        # DcBdDrawer
    0x07: "bonnet_removed",        # DcBonnetOff
    0x09: "cat_detected",          # DcCatDetect
    0x0C: "paused",                # DcUserPause
    0x14: "cycling",               # DcModeCycle
    0x16: "idle",                  # DcModeIdle
    0x26: "wifi_status",           # DcWifiStatus
    0x32: "setting_updated",
    0x33: "setting_updated",
    0x66: "connecting",
    0x67: "connecting",
    0x69: "zeroing",               # weight sensors zeroed; INFERRED
    0x6A: "lockout_key_pressed",   # DcxLockoutKeyhit
}
