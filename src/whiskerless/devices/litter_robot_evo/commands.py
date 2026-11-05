"""High-level Litter-Robot EVO command catalog.

Each builder returns a :class:`Command` carrying the encoded wire string, its
safety :class:`~whiskerless.safety.Hazard`, and the address and value the robot
echoes back when it applies the write. The echo carries the value the robot
actually applied, which is how a caller verifies a write.

Reads (:func:`read`, :func:`read_all`) return a register's current value for the
addresses in :data:`~.const.READABLE_REGISTERS`; :func:`read_all` is how a caller
learns the robot's state on connect, since the EVO has no state document.

Settings and most actions are the ones the Whisker app sends. The empty cycle,
which the app does not offer, starts the same way: a write of the matching robot
status. Panel button presses (bank 01 register 01) are not offered: the robot
reports them, but writing them is untested.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ...exceptions import ProtocolError
from ...safety import Hazard, classify_evo_code
from . import const
from .codec import encode_read, encode_write

"""Every command this module promises, on the same terms as the LR4 catalog."""
__all__ = [
    "Command",
    "change_filter",
    "clean_cycle",
    "empty_cycle",
    "power_off",
    "power_on",
    "read",
    "read_all",
    "reset_drawer_level",
    "set_clock",
    "set_cycle_delay",
    "set_keypad_lockout",
    "set_panel_brightness",
    "set_sleep_days",
    "set_sleep_schedule",
    "set_sleep_time",
    "set_wake_time",
]


@dataclass(frozen=True, slots=True)
class Command:
    """An encoded EVO command plus what its echo should look like."""

    code: str
    hazard: Hazard
    label: str
    bank: int
    register: int
    value: int
    #: Publish at QoS 0. An action is edge-triggered and carries no request id, so
    #: a redelivery after a lost PUBACK would run it twice; settings are idempotent.
    at_most_once: bool = False

    @property
    def address(self) -> tuple[int, int]:
        """``(bank, register)``, matched against the echo."""
        return (self.bank, self.register)


def _cmd(bank: int, register: int, value: int, label: str, *, at_most_once: bool = False) -> Command:
    code = encode_write(bank, register, value)
    return Command(
        code=code,
        hazard=classify_evo_code(code),
        label=label,
        bank=bank,
        register=register,
        value=value,
        at_most_once=at_most_once,
    )


def _setting(register: int, value: int, label: str) -> Command:
    return _cmd(const.Bank.SETTINGS, register, value, label)


def _action(register: int, value: int, label: str) -> Command:
    return _cmd(const.Bank.ROBOT, register, value, label, at_most_once=True)


# --- settings (SAFE) ---------------------------------------------------------
def set_panel_brightness(screen: int, led: int) -> Command:
    """Set the screen and status LED levels, each 1–100.

    The app's presets set both equal (Low 8, Medium 20, High 40); any pair in
    range is accepted. 0 is refused here because the robot replaces it with 50,
    the opposite of what someone asking for 0 wants.
    """
    for name, level in (("screen", screen), ("led", led)):
        if not const.BRIGHTNESS_MIN <= level <= const.BRIGHTNESS_MAX:
            raise ProtocolError(
                f"{name} brightness must be {const.BRIGHTNESS_MIN}-{const.BRIGHTNESS_MAX} "
                f"(got {level}); the robot replaces 0 with {const.BRIGHTNESS_ZERO_SUBSTITUTE}"
            )
    return _setting(
        const.SettingsRegister.PANEL_BRIGHTNESS, (screen << 8) | led, f"panelBrightness={screen}/{led}"
    )


def set_cycle_delay(minutes: int) -> Command:
    """Set the wait between a cat leaving and the clean cycle, in minutes.

    The app offers 3, 7 and 15; the register takes minutes directly.
    """
    if not 1 <= minutes <= 0xFF:
        raise ProtocolError(f"cycle delay must be 1-255 minutes (got {minutes})")
    return _setting(const.SettingsRegister.CYCLE_DELAY, minutes, f"cycleDelay={minutes}")


def set_keypad_lockout(enabled: bool) -> Command:
    """Lock or unlock the control panel. A 3-second press of Power also unlocks it."""
    return _setting(const.SettingsRegister.KEYPAD_LOCKOUT, int(enabled), f"keypadLockout={enabled}")


def set_sleep_days(days: Iterable[str]) -> Command:
    """Arm sleep mode on exactly ``days`` (weekday names); an empty set disarms it."""
    mask = 0
    for day in days:
        mask |= 1 << _weekday_index(day)
    return _setting(const.SettingsRegister.SLEEP_DAYS, mask, f"sleepDays=0x{mask:02X}")


def set_sleep_time(day: str, minutes: int) -> Command:
    """Set ``day``'s sleep time, in minutes after midnight."""
    return _setting(_sleep_register(day, wake=False), _minutes(minutes), f"sleepTime[{day}]={minutes}")


def set_wake_time(day: str, minutes: int) -> Command:
    """Set ``day``'s wake time, in minutes after midnight."""
    return _setting(_sleep_register(day, wake=True), _minutes(minutes), f"wakeTime[{day}]={minutes}")


def set_sleep_schedule(days: Iterable[str], sleep_minutes: int, wake_minutes: int) -> list[Command]:
    """Every write of a sleep schedule, in the order the app sends them.

    The same sleep and wake times go to all seven days, then the day mask last,
    so the schedule never arms against a half-written set. Publish the list as
    one message (see :meth:`LitterRobotEvoLink.publish_many`).
    """
    chosen = list(days)
    writes = [
        command
        for day in const.WEEKDAYS
        for command in (set_sleep_time(day, sleep_minutes), set_wake_time(day, wake_minutes))
    ]
    writes.append(set_sleep_days(chosen))
    return writes


_CLOCK_NAMES = ("weekday", "hour", "minute", "second", "day", "month", "year")


def set_clock(moment: datetime) -> list[Command]:
    """Every write that sets the robot's clock to ``moment``, read as local time.

    The sleep schedule runs on this clock. Whisker's cloud sets it each time the
    robot connects; a robot without the cloud keeps whatever it was last given.
    The weekday counts from Sunday = 0 and the year is two digits. Publish the
    list as one message (see :meth:`LitterRobotEvoLink.publish_many`).
    """
    if not 2000 <= moment.year <= 2099:
        raise ProtocolError(f"the robot's clock holds years 2000-2099 (got {moment.year})")
    values = (
        (moment.weekday() + 1) % 7,  # datetime counts from Monday = 0
        moment.hour,
        moment.minute,
        moment.second,
        moment.day,
        moment.month,
        moment.year % 100,
    )
    return [
        _setting(register, value, f"clock.{name}={value}")
        for register, name, value in zip(const.CLOCK_REGS, _CLOCK_NAMES, values, strict=True)
    ]


# --- actions (SAFE, except power off) ----------------------------------------
def clean_cycle() -> Command:
    """Run a clean cycle."""
    return _action(const.RobotRegister.ROBOT_STATUS, const.RobotCommand.CLEAN_CYCLE, "cleanCycle")


def empty_cycle() -> Command:
    """Empty the globe: every gram of litter goes into the waste drawer.

    The same action as holding Cycle on the panel. **The globe then stops at the
    dump position and stays there until Cycle is pressed on the panel**, which
    sends it home (cycle step 7). This catalog has no command for that press:
    panel-press writes are untested.
    """
    return _action(const.RobotRegister.ROBOT_STATUS, const.RobotCommand.EMPTY_CYCLE, "emptyCycle")


def change_filter() -> Command:
    """Start a filter change: the globe rotates for bonnet access.

    The robot then waits for the bonnet to come off and go back on, and for a
    press of Connect, before it returns home.
    """
    return _action(const.RobotRegister.ROBOT_STATUS, const.RobotCommand.CHANGE_FILTER, "changeFilter")


def reset_drawer_level() -> Command:
    """Zero the drawer counters, after the drawer is emptied."""
    return _action(const.RobotRegister.DRAWER_LEVEL_RESET, 1, "resetDrawerLevel")


def power_on() -> Command:
    """Power the robot on. It stays connected while off, so this reaches it."""
    return _action(const.RobotRegister.POWER, 1, "powerOn")


def power_off() -> Command:
    """Power the robot off. DANGEROUS: it stops cleaning until powered back on."""
    return _action(const.RobotRegister.POWER, 0, "powerOff")


# --- reads (SAFE) ------------------------------------------------------------
def read(bank: int, register: int) -> Command:
    """Read one register. The reply is a ``query`` message carrying its value.

    Any address may be read, but only those in ``const.READABLE_REGISTERS`` answer
    with their value; the rest answer with 0 whatever they hold.
    """
    code = encode_read(bank, register)
    return Command(
        code=code,
        hazard=classify_evo_code(code),
        label=f"read[{bank:02X}/{register:02X}]",
        bank=bank,
        register=register,
        value=0,
    )


def read_all() -> list[Command]:
    """A read of every readable register, in address order.

    Publish the list as one message (see :meth:`LitterRobotEvoLink.publish_many`):
    the robot answers with one ``query`` message holding one element per read, in
    request order.
    """
    return [read(bank, register) for bank, register in sorted(const.READABLE_REGISTERS)]


# --- helpers -----------------------------------------------------------------
def _weekday_index(day: str) -> int:
    try:
        return const.WEEKDAYS.index(day.strip().lower())
    except ValueError as exc:
        raise ProtocolError(f"unknown weekday {day!r}; expected one of {', '.join(const.WEEKDAYS)}") from exc


def _sleep_register(day: str, *, wake: bool) -> int:
    sleep, wake_register = const.SLEEP_SCHEDULE_REGS[const.WEEKDAYS[_weekday_index(day)]]
    return wake_register if wake else sleep


def _minutes(minutes: int) -> int:
    if not 0 <= minutes < 24 * 60:
        raise ProtocolError(f"time must be 0-1439 minutes after midnight (got {minutes})")
    return minutes
