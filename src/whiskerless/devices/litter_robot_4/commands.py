"""High-level Litter-Robot 4 command catalog.

Each builder returns a :class:`Command` carrying the encoded wire string, its
safety :class:`~whiskerless.safety.Hazard`, and — for settings writes — the
register/value to read back afterward (the firmware commits some writes with
variable latency, so callers verify and retry; see ``protocol.write_setting``).

Clean cycle and panel reset ARE exposed, as synthesised panel button presses on
register ``0x01`` — live-proven, three trials. Both are MOTOR-classified and refused
without ``allow_motor``. powerOn/powerOff and emptyCycle stay absent: they are not
panel buttons and their triggers remain unknown.
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
    #: Publish at QoS 0 instead of 1. Settings writes are idempotent, so
    #: at-least-once delivery is free; a panel button press is edge-triggered and
    #: carries no request id, so a redelivery after a lost PUBACK would run a
    #: second cycle. A press that goes missing is recoverable; a doubled one is not.
    at_most_once: bool = False


def is_edge_triggered(code: str) -> bool:
    """True for a panel-button write, which must never be delivered twice."""
    from ...safety import CommandType, parse_code

    ctype, register, _ = parse_code(code)
    return ctype is CommandType.WRITE and register == const.Register.PANEL_BUTTON


def _cmd(
    code: str,
    label: str,
    *,
    register: int | None = None,
    value: int | None = None,
    at_most_once: bool = False,
) -> Command:
    return Command(
        code=code,
        hazard=classify_code(code),
        label=label,
        register=register,
        value=value,
        at_most_once=at_most_once,
    )


# --- report / read macros (SAFE) ---------------------------------------------
def request_state() -> Command:
    """Ask the robot to publish its full named state document."""
    return _cmd(encode_write(const.Opcode.REQUEST_STATE, 0), "requestState")


def report_schedule() -> Command:
    """Ask for `0xA1`. Answers with `wifiRssi` alone, despite the name."""
    return _cmd(encode_write(const.Opcode.REPORT_SCHEDULE, 0), "reportSchedule")


def report_wifi_event() -> Command:
    """Ask for `0xA7`. Answers with an empty `data` array on an idle robot."""
    return _cmd(encode_write(const.Opcode.REPORT_WIFI_EVENT, 0), "reportWifiEvent")


def report_tof() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_TOF, 0), "reportToF")


def report_version() -> Command:
    return _cmd(encode_write(const.Opcode.REPORT_VERSION, 0), "reportVersion")


def read_register(register: int) -> Command:
    """A type-1 read of any register (the safest possible operation)."""
    return _cmd(encode_read(register), f"read 0x{register:02X}", register=register)


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


def clean_cycle() -> Command:
    """Run a clean cycle, by synthesising a press of the panel Cycle button.

    Classified MOTOR: this turns the globe, so it needs ``allow_motor``. The
    firmware's own pinch, cat-detect and bonnet interlocks still apply — they
    live in the PIC and no command overrides them.
    """
    return _cmd(
        encode_write(const.Register.PANEL_BUTTON, const.PANEL_BUTTON_CYCLE),
        "cleanCycle",
        at_most_once=True,
        register=const.Register.PANEL_BUTTON,
        value=const.PANEL_BUTTON_CYCLE,
    )


def panel_reset() -> Command:
    """Press the panel Reset button: acknowledge a full alarm, clear a fault.

    Classified MOTOR despite sounding harmless: from idle it only acknowledges an
    alarm, but during a cycle it releases a cat-interrupt pause — the interlock
    that holds the globe still while something is inside it.
    """
    return _cmd(
        encode_write(const.Register.PANEL_BUTTON, const.PANEL_BUTTON_RESET),
        "panelReset",
        at_most_once=True,
        register=const.Register.PANEL_BUTTON,
        value=const.PANEL_BUTTON_RESET,
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


def set_panel_sleep_times(minutes_since_midnight: int) -> tuple[Command, ...]:
    """Sleep time for every weekday — the only way to move the unified schedule.

    `0x1B` looks like the setting for this but is a read-only view of whichever
    weekday pair is in force today, so writing it is refused; the per-weekday
    registers are the actual storage.
    """
    return tuple(
        set_weekday_sleep_time(day, minutes_since_midnight) for day in const.WEEKDAYS
    )


def set_panel_wake_times(minutes_since_midnight: int) -> tuple[Command, ...]:
    """Wake time for every weekday. `0x1C` is read-only, as `0x1B` is."""
    return tuple(
        set_weekday_wake_time(day, minutes_since_midnight) for day in const.WEEKDAYS
    )


def _weekday_regs(weekday: str) -> tuple[int, int]:
    key = weekday.strip().lower()
    if key not in const.WEEKDAY_SCHEDULE_REGS:
        raise ValueError(f"unknown weekday {weekday!r}; expected one of {const.WEEKDAYS}")
    return const.WEEKDAY_SCHEDULE_REGS[key]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
