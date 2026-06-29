"""High-level command catalog — codes, hazards, and read-back metadata."""

from __future__ import annotations

from whiskerless.devices.litter_robot_4 import commands, const
from whiskerless.safety import Hazard


def test_request_state() -> None:
    cmd = commands.request_state()
    assert cmd.code == "0x02A00000"
    assert cmd.hazard is Hazard.SAFE


def test_settings_carry_register_and_value() -> None:
    cmd = commands.set_night_light_mode(2)
    assert cmd.code == "0x02180002"
    assert cmd.register == const.Register.NIGHT_LIGHT_MODE
    assert cmd.value == 2
    assert cmd.hazard is Hazard.SAFE


def test_settings_encodings() -> None:
    assert commands.set_night_light_brightness(100).code == "0x02190064"
    assert commands.set_clean_cycle_wait_minutes(15).code == "0x0216000F"
    assert commands.set_keypad_lockout(True).code == "0x02170001"
    assert commands.set_keypad_lockout(False).code == "0x02170000"
    assert commands.set_panel_brightness(0x32, 0x32).code == "0x020E3232"
    assert commands.set_panel_sleep_time(1320).code == "0x021B0528"


def test_brightness_is_clamped() -> None:
    assert commands.set_night_light_brightness(200).value == 100
    assert commands.set_night_light_brightness(-5).value == 0


def test_weekday_schedule_registers() -> None:
    # Sun→Sat, sleep-then-wake across 0x1E–0x2B.
    assert commands.set_weekday_sleep_time("sunday", 0).register == 0x1E
    assert commands.set_weekday_wake_time("sunday", 0).register == 0x1F
    assert commands.set_weekday_sleep_time("saturday", 0).register == 0x2A
    assert commands.set_weekday_wake_time("saturday", 0).register == 0x2B


def test_read_register() -> None:
    cmd = commands.read_register(0x47)
    assert cmd.code == "0x01470000"
    assert cmd.hazard is Hazard.SAFE
    assert cmd.register == 0x47
