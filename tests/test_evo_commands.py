"""The EVO command catalog: encodings, validation and safety classes."""

from __future__ import annotations

from datetime import datetime

import pytest

from whiskerless.devices.litter_robot_evo import commands, const
from whiskerless.exceptions import ProtocolError
from whiskerless.safety import Hazard


def test_panel_brightness_packs_screen_above_led() -> None:
    command = commands.set_panel_brightness(8, 1)
    assert command.code == "0x0202010801"
    assert command.address == (0x02, 0x01)
    assert command.value == 0x0801
    assert command.hazard is Hazard.SAFE
    assert not command.at_most_once


@pytest.mark.parametrize(("screen", "led"), [(0, 8), (8, 0), (101, 8), (8, 101)])
def test_panel_brightness_out_of_range_is_refused(screen: int, led: int) -> None:
    with pytest.raises(ProtocolError, match="replaces 0 with 50"):
        commands.set_panel_brightness(screen, led)


def test_the_apps_presets_encode_as_it_sends_them() -> None:
    assert commands.set_panel_brightness(8, 8).code == "0x0202010808"
    assert commands.set_panel_brightness(20, 20).code == "0x0202011414"
    assert commands.set_panel_brightness(40, 40).code == "0x0202012828"


def test_cycle_delay_and_lockout() -> None:
    assert commands.set_cycle_delay(15).code == "0x020209000F"
    assert commands.set_keypad_lockout(True).code == "0x02020A0001"
    assert commands.set_keypad_lockout(False).code == "0x02020A0000"
    with pytest.raises(ProtocolError):
        commands.set_cycle_delay(0)


def test_sleep_days_is_a_sunday_first_mask() -> None:
    assert commands.set_sleep_days(["Sunday", "saturday"]).code == "0x0202100041"
    assert commands.set_sleep_days([]).code == "0x0202100000"
    with pytest.raises(ProtocolError, match="unknown weekday"):
        commands.set_sleep_days(["funday"])


def test_sleep_and_wake_times_address_each_day() -> None:
    assert commands.set_sleep_time("monday", 0).code == "0x0202130000"
    assert commands.set_wake_time("monday", 720).code == "0x02021402D0"
    with pytest.raises(ProtocolError, match="0-1439"):
        commands.set_wake_time("monday", 1440)


def test_a_schedule_writes_every_day_then_the_mask_last() -> None:
    writes = commands.set_sleep_schedule(["sunday", "saturday"], 0, 720)
    assert len(writes) == 15
    assert [w.register for w in writes[:14]] == list(range(0x11, 0x1F))
    assert writes[-1].code == "0x0202100041"
    assert all(w.hazard is Hazard.SAFE for w in writes)


def test_actions_are_at_most_once_and_encode_as_the_app_sends_them() -> None:
    expected = {
        commands.clean_cycle: "0x020103000A",
        commands.empty_cycle: "0x020103000B",
        commands.change_filter: "0x020103000C",
        commands.reset_drawer_level: "0x0201220001",
        commands.power_on: "0x0201140001",
    }
    for build, code in expected.items():
        command = build()
        assert command.code == code
        assert command.at_most_once
        assert command.hazard is Hazard.SAFE


def test_a_read_is_a_safe_type_01_element() -> None:
    command = commands.read(0x02, 0x09)
    assert command.code == "0x0102090000"
    assert command.hazard is Hazard.SAFE
    assert command.address == (0x02, 0x09)
    assert command.label == "read[02/09]"


def test_read_all_reads_every_readable_register_in_address_order() -> None:
    reads = commands.read_all()
    assert [r.address for r in reads] == sorted(const.READABLE_REGISTERS)
    assert all(r.code.startswith("0x01") and r.hazard is Hazard.SAFE for r in reads)
    assert (0x01, 0x02) not in {r.address for r in reads}  # the display code cannot be read


def test_power_off_is_dangerous() -> None:
    command = commands.power_off()
    assert command.code == "0x0201140000"
    assert command.hazard is Hazard.DANGEROUS


def test_set_clock_writes_the_seven_clock_registers_in_order() -> None:
    writes = commands.set_clock(datetime(2026, 1, 30, 8, 1, 28))  # synthetic: a Friday
    assert [w.code for w in writes] == [
        "0x0202020005",  # weekday, Sunday = 0
        "0x0202030008",  # hour
        "0x0202040001",  # minute
        "0x020205001C",  # second
        "0x020206001E",  # day of the month
        "0x0202070001",  # month
        "0x020208001A",  # year, two digits
    ]
    assert all(w.hazard is Hazard.SAFE and not w.at_most_once for w in writes)
    assert [w.register for w in writes] == list(const.CLOCK_REGS)


def test_set_clock_counts_weekdays_from_sunday() -> None:
    assert commands.set_clock(datetime(2026, 2, 1))[0].value == 0  # synthetic Sunday
    assert commands.set_clock(datetime(2026, 1, 31))[0].value == 6  # synthetic Saturday


def test_set_clock_refuses_years_it_cannot_hold() -> None:
    with pytest.raises(ProtocolError, match="2000-2099"):
        commands.set_clock(datetime(2100, 1, 1))
