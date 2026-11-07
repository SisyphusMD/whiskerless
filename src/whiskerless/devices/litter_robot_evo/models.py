"""Typed Litter-Robot EVO state, built from reads, telemetry and write echoes.

The EVO has no state document, but most registers can be read one by one
(:data:`~.const.READABLE_REGISTERS`): a read of every readable register, sent as
one message, fills in status, power, bonnet, drawer, odometers and every setting
at once. The rest (the display code, the weight sensor, the drawer counters)
answer a read with 0, so they fill in only from telemetry. Every telemetry
element, write echo and read reply updates the register it names, and a field
stays ``None`` until the robot has reported it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import const
from .codec import ActivityReading
from .protocol import ActivityMessage, EventMessage, PawprintMessage

__all__ = [
    "LitterRobotEvoState",
    "apply_message",
]

_ROBOT = const.Bank.ROBOT
_SETTINGS = const.Bank.SETTINGS
#: Sleep-schedule register -> (day, is the wake time).
_SLEEP_REGS: dict[int, tuple[str, bool]] = {
    **{sleep: (day, False) for day, (sleep, _) in const.SLEEP_SCHEDULE_REGS.items()},
    **{wake: (day, True) for day, (_, wake) in const.SLEEP_SCHEDULE_REGS.items()},
}


@dataclass(frozen=True, slots=True)
class LitterRobotEvoState:
    """A snapshot of what the robot has reported. ``None`` means "not reported yet"."""

    # Status / panel
    robot_status: str | None = None
    robot_status_raw: int | None = None
    display: str | None = None
    display_raw: int | None = None
    last_button: int | None = None
    cycle_step: int | None = None
    cycle_phase: int | None = None

    # Hardware
    power_on: bool | None = None
    bonnet_removed: bool | None = None
    drawer_removed: bool | None = None
    #: Raw signed reading of the weight sensor; its scale is not yet known.
    weight_raw: int | None = None
    weight_settling: bool | None = None
    #: Power-cycle odometer, reported at each power-on.
    odometer_power_cycles: int | None = None
    #: Empty-cycle odometer.
    odometer_empty_cycles: int | None = None
    #: Weight from the last `usage` event, in pounds.
    last_weight_lb: float | None = None
    #: The pet profile the robot last identified, and its confidence.
    last_pet_profile: str | None = None
    last_pet_confidence: float | None = None
    #: Raw drawer fullness counter, zeroed by the drawer reset.
    drawer_counter: int | None = None
    #: The main-board id (bank 09 register 08), matching the robot firmware string.
    main_board_id: int | None = None

    # Settings
    screen_brightness: int | None = None
    led_brightness: int | None = None
    cycle_delay_minutes: int | None = None
    keypad_lockout: bool | None = None
    #: The raw sleep-day mask, or None when the register has not been reported.
    sleep_mask: int | None = None
    sleep_days: frozenset[str] = frozenset()
    sleep_times: dict[str, int] = field(default_factory=dict)
    wake_times: dict[str, int] = field(default_factory=dict)

    #: The last value of every address reported, decoded or not.
    registers: dict[tuple[int, int], int] = field(default_factory=dict)

    @property
    def is_cleaning(self) -> bool | None:
        """True while a clean cycle runs, from the robot status."""
        if self.robot_status_raw is None:
            return None
        return self.robot_status_raw == const.RobotCommand.CLEAN_CYCLE

    @property
    def is_emptying(self) -> bool | None:
        """True while an empty cycle runs, from the robot status."""
        if self.robot_status_raw is None:
            return None
        return self.robot_status_raw == const.RobotCommand.EMPTY_CYCLE

    def with_readings(self, readings: Iterable[ActivityReading]) -> LitterRobotEvoState:
        """Return a new state with ``readings`` applied in order."""
        changes: dict[str, object] = {}
        registers = dict(self.registers)
        sleep_times = dict(self.sleep_times)
        wake_times = dict(self.wake_times)
        for reading in readings:
            registers[reading.address] = reading.value
            changes.update(_decode(reading, sleep_times, wake_times))
        changes["registers"] = registers
        changes["sleep_times"] = sleep_times
        changes["wake_times"] = wake_times
        return dataclasses.replace(self, **changes)  # type: ignore[arg-type]


def apply_message(
    state: LitterRobotEvoState, message: ActivityMessage | EventMessage | PawprintMessage
) -> LitterRobotEvoState:
    """Fold one parsed message into ``state``.

    A read reply (``query``) carries one element per register read, each with the
    register's current value; elements for addresses outside
    :data:`~.const.READABLE_REGISTERS` are dropped, because those registers answer
    a read with 0 and a 0 must not overwrite a real value. Event records carry
    current register values and are applied like telemetry. A ``pawprint``
    ``pet_id_match`` records the identified pet; other ``pawprint`` messages carry
    no state.
    """
    if isinstance(message, ActivityMessage):
        if message.query:
            readable = [r for r in message.readings if r.address in const.READABLE_REGISTERS]
            return state.with_readings(readable) if readable else state
        return state.with_readings(message.readings)
    if isinstance(message, EventMessage):
        return state.with_readings(message.readings)
    match = message.pet_id_match
    if match is None:
        return state
    return dataclasses.replace(
        state, last_pet_profile=match.profile, last_pet_confidence=match.confidence
    )


def _decode(
    reading: ActivityReading, sleep_times: dict[str, int], wake_times: dict[str, int]
) -> dict[str, object]:
    bank, register, value = reading.bank, reading.register, reading.value
    if bank == _ROBOT:
        return _decode_robot(register, value)
    if bank == _SETTINGS:
        return _decode_settings(register, value, sleep_times, wake_times)
    if bank == const.Bank.SENSORS:
        if register == const.SensorRegister.WEIGHT:
            return {"weight_raw": reading.signed_value}
        if register == const.SensorRegister.DRAWER_COUNTER:
            return {"drawer_counter": value}
    if bank == const.Bank.USAGE and register == const.UsageRegister.WEIGHT:
        return {"last_weight_lb": value / 100}
    if bank == const.Bank.MEASURE and register == const.MeasureRegister.WEIGHT_SETTLING:
        return {"weight_settling": bool(value)}
    if bank == const.Bank.BOARD and register == const.BoardRegister.MAIN_BOARD_ID:
        return {"main_board_id": value}
    return {}


def _decode_robot(register: int, value: int) -> dict[str, object]:
    reg = const.RobotRegister
    if register == reg.ROBOT_STATUS:
        return {"robot_status": const.ROBOT_STATUS.get(value), "robot_status_raw": value}
    if register == reg.DISPLAY_CODE:
        return {"display": const.DISPLAY_CODES.get(value), "display_raw": value}
    if register == reg.BUTTON:
        return {"last_button": value}
    if register == reg.CYCLE_STEP:
        return {"cycle_step": value}
    if register == reg.CYCLE_PHASE:
        return {"cycle_phase": value}
    if register == reg.POWER:
        return {"power_on": bool(value)}
    if register == reg.POWER_CYCLES:
        return {"odometer_power_cycles": value}
    if register == reg.EMPTY_CYCLES:
        return {"odometer_empty_cycles": value}
    if register == reg.BONNET_REMOVED:
        return {"bonnet_removed": bool(value)}
    if register == reg.DRAWER_REMOVED:
        return {"drawer_removed": bool(value)}
    return {}


def _decode_settings(
    register: int, value: int, sleep_times: dict[str, int], wake_times: dict[str, int]
) -> dict[str, object]:
    reg = const.SettingsRegister
    if register == reg.PANEL_BRIGHTNESS:
        return {"screen_brightness": value >> 8, "led_brightness": value & 0xFF}
    if register == reg.CYCLE_DELAY:
        return {"cycle_delay_minutes": value}
    if register == reg.KEYPAD_LOCKOUT:
        return {"keypad_lockout": bool(value)}
    if register == reg.SLEEP_DAYS:
        days = frozenset(day for i, day in enumerate(const.WEEKDAYS) if value & (1 << i))
        return {"sleep_mask": value, "sleep_days": days}
    if register in _SLEEP_REGS:
        day, is_wake = _SLEEP_REGS[register]
        (wake_times if is_wake else sleep_times)[day] = value
    return {}
