"""High-level Litter-Robot 4 command catalog.

Each builder returns a :class:`Command` carrying the encoded wire string, its
safety :class:`~whiskerless.safety.Hazard`, and — for settings writes — the
register/value to read back afterward (the firmware commits some writes with
variable latency, so callers verify and retry; see ``protocol.write_setting``).

Only PROVEN-safe actions are exposed. powerOn/powerOff/emptyCycle/shortResetPress
are deliberately absent: reverse-engineering could not pin their register+value
to actionable confidence, and the candidate writes land in the dangerous control
band. They are tracked as open items in the docs, not shipped as guesses.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...safety import Hazard, classify_code
from . import const
from .codec import encode_read, encode_write


@dataclass(frozen=True, slots=True)
class Command:
    """An encoded command plus the metadata needed to send and verify it."""

    code: str
    hazard: Hazard
    label: str
    register: int | None = None  # settings-write target, for read-back verify
    value: int | None = None     # 16-bit value written, expected on read-back


def _cmd(code: str, label: str, *, register: int | None = None, value: int | None = None) -> Command:
    return Command(code=code, hazard=classify_code(code), label=label, register=register, value=value)


# --- report / read macros (SAFE) ---------------------------------------------
def request_state() -> Command:
    """Ask the robot to publish its full named state document."""
    return _cmd(encode_write(const.Opcode.REQUEST_STATE, 0), "requestState")


def report_schedule() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_SCHEDULE, 0), "reportSchedule")


def report_wifi_event() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_WIFI_EVENT, 0), "reportWifiEvent")


def report_tof() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_TOF, 0), "reportToF")


def report_version() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_VERSION, 0), "reportVersion")


def read_register(register: int) -> Command:
    """A type-1 read of any register (the safest possible operation)."""
    return _cmd(encode_read(register), f"read 0x{register:02X}", register=register)


# --- motor (gated) -----------------------------------------------------------
def clean_cycle() -> Command:
    """Run a clean cycle. Drives the globe motor — gate behind confirmation."""
    return _cmd(encode_write(const.Opcode.CLEAN_CYCLE, 0), "cleanCycle")


# --- settings writes (SAFE, reversible, read-back-verified) ------------------
def set_night_light_mode(mode: int) -> Command:
    """0 = off, 1 = on, 2 = auto."""
    mode = _clamp(mode, 0, 2)
    return _cmd(
        encode_write(const.Register.NIGHT_LIGHT_MODE, mode),
        "setNightLightMode",
        register=const.Register.NIGHT_LIGHT_MODE,
        value=mode,
    )


def set_night_light_brightness(percent: int) -> Command:
    """Night-light brightness, 0–100 % (direct)."""
    percent = _clamp(percent, 0, 100)
    return _cmd(
        encode_write(const.Register.NIGHT_LIGHT_BRIGHTNESS, percent),
        "setNightLightBrightness",
        register=const.Register.NIGHT_LIGHT_BRIGHTNESS,
        value=percent,
    )


def set_clean_cycle_wait_minutes(minutes: int) -> Command:
    """Minutes the robot waits after a cat leaves before cycling."""
    minutes = _clamp(minutes, 0, 255)
    return _cmd(
        encode_write(const.Register.CLEAN_CYCLE_WAIT_TIME, minutes),
        "setCleanCycleWait",
        register=const.Register.CLEAN_CYCLE_WAIT_TIME,
        value=minutes,
    )


def set_keypad_lockout(enabled: bool) -> Command:
    value = 1 if enabled else 0
    return _cmd(
        encode_write(const.Register.IS_KEYPAD_LOCKOUT, value),
        "setKeypadLockout",
        register=const.Register.IS_KEYPAD_LOCKOUT,
        value=value,
    )


def set_panel_brightness(high: int, low: int) -> Command:
    """Panel brightness — packed hi-byte = High level, lo-byte = Low level."""
    high = _clamp(high, 0, 255)
    low = _clamp(low, 0, 255)
    packed = (high << 8) | low
    return _cmd(
        encode_write(const.Register.PANEL_BRIGHTNESS, packed),
        "setPanelBrightness",
        register=const.Register.PANEL_BRIGHTNESS,
        value=packed,
    )


def set_panel_sleep_mode(enabled: bool) -> Command:
    value = 1 if enabled else 0
    return _cmd(
        encode_write(const.Register.IS_PANEL_SLEEP_MODE, value),
        "setPanelSleepMode",
        register=const.Register.IS_PANEL_SLEEP_MODE,
        value=value,
    )


def set_panel_sleep_time(minutes_since_midnight: int) -> Command:
    minutes = _clamp(minutes_since_midnight, 0, 1439)
    return _cmd(
        encode_write(const.Register.PANEL_SLEEP_TIME, minutes),
        "setPanelSleepTime",
        register=const.Register.PANEL_SLEEP_TIME,
        value=minutes,
    )


def set_panel_wake_time(minutes_since_midnight: int) -> Command:
    minutes = _clamp(minutes_since_midnight, 0, 1439)
    return _cmd(
        encode_write(const.Register.PANEL_WAKE_TIME, minutes),
        "setPanelWakeTime",
        register=const.Register.PANEL_WAKE_TIME,
        value=minutes,
    )


def set_weekday_sleep_enabled(enabled: bool) -> Command:
    value = 1 if enabled else 0
    return _cmd(
        encode_write(const.Register.WEEKDAY_SLEEP_MODE_ENABLED, value),
        "setWeekdaySleepEnabled",
        register=const.Register.WEEKDAY_SLEEP_MODE_ENABLED,
        value=value,
    )


def set_weekday_sleep_time(weekday: str, minutes_since_midnight: int) -> Command:
    sleep_reg, _ = _weekday_regs(weekday)
    minutes = _clamp(minutes_since_midnight, 0, 1439)
    return _cmd(
        encode_write(sleep_reg, minutes),
        f"setWeekdaySleepTime[{weekday}]",
        register=sleep_reg,
        value=minutes,
    )


def set_weekday_wake_time(weekday: str, minutes_since_midnight: int) -> Command:
    _, wake_reg = _weekday_regs(weekday)
    minutes = _clamp(minutes_since_midnight, 0, 1439)
    return _cmd(
        encode_write(wake_reg, minutes),
        f"setWeekdayWakeTime[{weekday}]",
        register=wake_reg,
        value=minutes,
    )


def _weekday_regs(weekday: str) -> tuple[int, int]:
    key = weekday.strip().lower()
    if key not in const.WEEKDAY_SCHEDULE_REGS:
        raise ValueError(f"unknown weekday {weekday!r}; expected one of {const.WEEKDAYS}")
    return const.WEEKDAY_SCHEDULE_REGS[key]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
