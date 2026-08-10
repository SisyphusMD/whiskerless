"""High-level command catalog — codes, hazards, and read-back metadata."""

from __future__ import annotations

import pytest

from whiskerless.devices.litter_robot_4 import commands, const
from whiskerless.safety import Hazard, classify_code


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


def test_a_schedule_write_targets_every_weekday_not_the_mirror() -> None:
    """0x1B/0x1C are a read-only view of today's pair, so writing them does nothing.

    The schedule is stored per weekday, Sunday-first, sleep-then-wake.
    """
    sleeps = commands.set_panel_sleep_times(1290)
    assert [c.register for c in sleeps] == list(range(0x1E, 0x2C, 2))
    assert all(c.value == 1290 for c in sleeps)
    assert not any(c.register == const.Register.PANEL_SLEEP_TIME for c in sleeps)

    wakes = commands.set_panel_wake_times(420)
    assert [c.register for c in wakes] == list(range(0x1F, 0x2C, 2))
    assert all(c.value == 420 for c in wakes)


def test_panel_brightness_clamps_into_the_packed_value() -> None:
    """Callers verify against `value`, so the clamp has to be visible there.

    Comparing a read-back with the caller's out-of-range number would call a
    clamped-but-successfully-applied write a failure.
    """
    assert commands.set_panel_brightness(300, -5).value == (255 << 8) | 0
    assert commands.set_panel_brightness(90, 100).value == (90 << 8) | 100


def test_button_presses_ask_for_at_most_once_delivery() -> None:
    """A doubled press runs a second cycle; a missed one is just pressed again.

    Settings writes stay at-least-once because rewriting the same value is free.
    """
    assert commands.clean_cycle().at_most_once
    assert commands.panel_reset().at_most_once
    assert not commands.set_night_light_brightness(50).at_most_once
    assert not commands.request_state().at_most_once


def test_enabling_the_sleep_schedule_arms_every_day() -> None:
    """Writing 1 would arm Sunday only — 0x1D is a per-day bitmask."""
    assert commands.set_weekday_sleep_enabled(True).value == const.WEEKDAY_SLEEP_ALL_DAYS
    assert commands.set_weekday_sleep_enabled(False).value == 0


def test_the_destructive_presses_encode_the_captured_codes() -> None:
    """Both are captured from physical presses and never written.

    Wrong bits here are expensive in a way the other commands are not: 0x0C02 is
    a factory reset and 0x1402 simulates a plug pull, and both are one or two
    bits from these.
    """
    assert commands.empty_cycle().code == "0x02010801"
    assert commands.power_toggle().code == "0x02010101"
    for command in (commands.empty_cycle(), commands.power_toggle()):
        assert command.at_most_once, "an edge-triggered press must never be retried"


@pytest.mark.parametrize(
    ("builder", "code"),
    [
        ("report_schedule", "0x02A10000"),
        ("report_wifi_event", "0x02A70000"),
        ("report_tof", "0x02A90000"),
        ("report_version", "0x02AE0000"),
    ],
)
def test_every_report_macro_encodes_its_opcode(builder: str, code: str) -> None:
    """All four are SAFE only at value 0; the value is what makes them a jump."""
    command = getattr(commands, builder)()
    assert command.code == code
    assert classify_code(command.code) is Hazard.SAFE


def test_the_single_day_wake_register_is_addressable() -> None:
    command = commands.set_panel_wake_time(420)
    assert command.register == const.Register.PANEL_WAKE_TIME
    assert command.value == 420


def test_an_unknown_weekday_names_the_ones_that_exist() -> None:
    """The day mapping is inferred, so a typo must not silently write Sunday."""
    with pytest.raises(ValueError, match="unknown weekday"):
        commands.set_weekday_sleep_time("funday", 1290)
