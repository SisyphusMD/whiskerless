"""Defensive state decoding — raw ints or cloud strings, partial payloads."""

from __future__ import annotations

import pytest

from whiskerless.devices.litter_robot_4.models import (
    LitterRobot4State,
    every_weekday_is,
    litter_level_percent_from_mm,
)


def test_enum_from_raw_int() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 10, "nightLightMode": 2})
    assert state.robot_status == "clean_cycle"
    assert state.night_light_mode == "auto"
    assert state.is_cleaning is True


def test_enum_from_cloud_string() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": "ROBOT_IDLE"})
    assert state.robot_status == "ready"
    assert state.is_cleaning is False


def test_unknown_enum_int_is_labelled() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 99})
    assert state.robot_status == "unknown_99"


def test_bools_accept_int_and_string() -> None:
    assert LitterRobot4State.from_state_doc({"isKeypadLockout": 1}).keypad_lockout is True
    assert LitterRobot4State.from_state_doc({"isKeypadLockout": "false"}).keypad_lockout is False
    assert LitterRobot4State.from_state_doc({"isKeypadLockout": 0}).keypad_lockout is False


@pytest.mark.parametrize(("raw", "expected"), [(0, False), (1, True), (2, False), (3, True)])
def test_cat_detected_uses_the_cat_correlated_bit(raw: int, expected: bool) -> None:
    assert LitterRobot4State.from_state_doc({"catDetect": raw}).cat_detected is expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("true", True), ("false", False), ("CAT_DETECT", None)]
)
def test_cat_detected_tolerates_cloud_style_strings(raw: str, expected: bool | None) -> None:
    assert LitterRobot4State.from_state_doc({"catDetect": raw}).cat_detected is expected


def test_litter_level_falls_back_to_mm() -> None:
    state = LitterRobot4State.from_state_doc({"litterLevel": 460})
    assert state.litter_level_mm == 460
    assert state.litter_level == litter_level_percent_from_mm(460)


def test_litter_level_prefers_percentage() -> None:
    state = LitterRobot4State.from_state_doc({"litterLevel": 460, "litterLevelPercentage": 70})
    assert state.litter_level == 70


def test_cat_weight_float() -> None:
    assert LitterRobot4State.from_state_doc({"catWeight": 8.5}).cat_weight == 8.5


def test_partial_payload_degrades_to_none() -> None:
    state = LitterRobot4State.from_state_doc({})
    assert state.robot_status is None
    assert state.litter_level is None
    assert state.keypad_lockout is None


@pytest.mark.parametrize(("mm", "expected_floor"), [(440, 100), (1000, 0)])
def test_litter_level_percent_bounds(mm: int, expected_floor: int) -> None:
    assert litter_level_percent_from_mm(mm) >= 0
    if mm >= 1000:
        assert litter_level_percent_from_mm(mm) == 0


# --- ESP 1.4.x firmware decode (values live-captured from a real 1.4.4 robot) --

V14 = {"espFirmware": "1.4.4"}


def test_esp14_status_10_is_cleaning() -> None:
    # On 1.4.x, 10 = clean cycle in progress (observed 15/15 cycles), NOT the
    # 1.1.x cat/weight pause.
    state = LitterRobot4State.from_state_doc({"robotStatus": 10, **V14})
    assert state.robot_status == "clean_cycle"
    assert state.is_cleaning is True


def test_status_10_is_cleaning_on_every_firmware() -> None:
    # Both captured firmwares agree; there is no version gate. The 1.1.75 case
    # is the narrated manual cycle in CAPTURE_1175_CYCLING below.
    for doc in ({"robotStatus": 10}, {"robotStatus": 10, "espFirmware": "1.1.75"}):
        state = LitterRobot4State.from_state_doc(doc)
        assert state.robot_status == "clean_cycle"
        assert state.is_cleaning is True


def test_status_13_is_the_power_up_cycle_not_the_clean_cycle() -> None:
    """13 is the boot cycle, not the clean cycle.

    Captured live across a panel Power off/on, held for the whole automatic cycle
    a robot runs on boot. It must suppress litter readings because the globe is
    turning, and it must not be confused with the ordinary clean cycle (10).
    """
    state = LitterRobot4State.from_state_doc({"robotStatus": 13, "litterLevel": 450})
    assert state.robot_status == "power_up_cycle"
    assert state.is_cleaning
    assert state.litter_level_mm is None


def test_esp14_new_status_values() -> None:
    cases = {5: "bonnet_removed", 6: "cat_sensor_timing", 7: "cat_sensor_timing", 25: "cat_detected"}
    for raw, slug in cases.items():
        assert LitterRobot4State.from_state_doc({"robotStatus": raw, **V14}).robot_status == slug


def test_unparsable_firmware_still_decodes() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 10, "espFirmware": "weird"})
    assert state.robot_status == "clean_cycle"


# Real payloads, trimmed from a narrated capture on LR4C654321 (ESP 1.1.75):
# the owner pressed Cycle, the robot ran a full cycle, and both docs below are
# verbatim field subsets of what landed on the broker.
CAPTURE_1175_CYCLING = {
    "robotStatus": 10,
    "robotCycleStatus": 4,
    "robotCycleState": 3,
    "catDetect": 0,
    "litterLevel": 575,
    "DFILevelPercent": 71,
    "isDFIFull": 0,
    "espFirmware": "1.1.75",
    "mbHardware": 10500,
    "mbBom": 3072,
    "mbSuite": 2,
    "mbRevision": 89,
}
CAPTURE_1175_IDLE = {
    "robotStatus": 4,
    "robotCycleStatus": 1,
    "robotCycleState": 1,
    "catDetect": 0,
    "litterLevel": 453,
    "DFILevelPercent": 71,
    "isDFIFull": 0,
    "espFirmware": "1.1.75",
}


def test_real_1175_capture_mid_cycle() -> None:
    state = LitterRobot4State.from_state_doc(CAPTURE_1175_CYCLING)
    assert state.robot_status == "clean_cycle"
    assert state.is_cleaning is True
    # catDetect is 0 for the whole cycle, which is what disproves the old
    # "10 = cat/weight pause" reading.
    assert state.cat_detected is False
    # 575 mm is the ToF reading the rotating globe, not the litter bed.
    assert state.litter_level is None
    assert state.litter_level_mm is None
    assert state.pic_firmware == "10500.3072.2.89"


def test_real_1175_capture_idle() -> None:
    state = LitterRobot4State.from_state_doc(CAPTURE_1175_IDLE)
    assert state.robot_status == "ready"
    assert state.is_cleaning is False
    assert state.litter_level_mm == 453
    assert state.waste_drawer_level == 71


def test_unmapped_cloud_string_defers_to_the_cycle_machine() -> None:
    # The firmware has string families we have never captured (the filter-change
    # wizard, for one). An unrecognized status must not read as "not cleaning",
    # or mid-cycle ToF garbage gets published as a litter level.
    state = LitterRobot4State.from_state_doc(
        {"robotStatus": "ROBOT_NOT_INVENTED_YET", "robotCycleStatus": 4, "litterLevel": 575}
    )
    assert state.is_cleaning is True
    assert state.litter_level_mm is None


def test_the_filter_wizard_suppresses_litter_readings() -> None:
    # The globe parks INVERTED for the whole wizard, so the ToF is not looking
    # at the litter bed even though this is not a clean cycle.
    state = LitterRobot4State.from_state_doc(
        {"robotStatus": "ROBOT_CHANGE_FILTER", "litterLevel": 575}
    )
    assert state.robot_status == "changing_filter"
    assert state.is_cleaning is False
    assert state.litter_level_mm is None


def test_known_idle_status_beats_stale_cycle_status() -> None:
    # A lagging robotCycleStatus must not make a resting robot report cleaning,
    # which would also blank both litter readings.
    state = LitterRobot4State.from_state_doc(
        {"robotStatus": 4, "robotCycleStatus": 4, "litterLevel": 453}
    )
    assert state.is_cleaning is False
    assert state.litter_level_mm == 453


def test_is_cleaning_falls_back_to_cycle_status() -> None:
    # Unmapped robotStatus int + active cycle machine (real 1.4.4 mid-cycle doc
    # shape) must still read as cleaning.
    state = LitterRobot4State.from_state_doc(
        {"robotStatus": 99, "robotCycleStatus": 4, "robotCycleState": 12, **V14}
    )
    assert state.is_cleaning is True


def test_litter_level_suppressed_while_cycling() -> None:
    # Captured mid-cycle doc read 574 mm on a 460 mm fill — ToF sees the globe.
    state = LitterRobot4State.from_state_doc(
        {"robotStatus": 10, "robotCycleStatus": 2, "robotCycleState": 12, "litterLevel": 574, **V14}
    )
    assert state.litter_level is None
    assert state.litter_level_mm is None


def test_litter_level_kept_while_ready() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 4, "litterLevel": 460, **V14})
    assert state.litter_level_mm == 460


def test_pic_firmware_composed_from_mb_fields() -> None:
    # Local docs carry the PIC identity as mb* ints; cloud shows "10535.2560.4.4".
    state = LitterRobot4State.from_state_doc(
        {"mbHardware": 10535, "mbBom": 2560, "mbSuite": 4, "mbRevision": 4}
    )
    assert state.pic_firmware == "10535.2560.4.4"


def test_pic_firmware_not_composed_from_zeros() -> None:
    state = LitterRobot4State.from_state_doc(
        {"mbHardware": 0, "mbBom": 0, "mbSuite": 0, "mbRevision": 0}
    )
    assert state.pic_firmware is None
def test_display_intensity_decoded() -> None:
    # Real 1.4.4 state doc carries DisplayIntensityHigh/Low as separate ints.
    state = LitterRobot4State.from_state_doc(
        {"DisplayIntensityHigh": 40, "DisplayIntensityLow": 50}
    )
    assert state.display_intensity_high == 40
    assert state.display_intensity_low == 50


# --- litter calibration -------------------------------------------------------


def test_calibration_pins_the_line_to_ninety_percent() -> None:
    # The cloud reports 0.9 for a robot sitting at its own optimalLitterLevel,
    # leaving headroom above so an overfill can still read higher.
    assert litter_level_percent_from_mm(453, full_mm=453) == 90


def test_calibration_is_per_robot() -> None:
    # Measured references differ across robots by ~10 mm; uncalibrated, that
    # same spread silently moves the answer.
    assert litter_level_percent_from_mm(459, full_mm=459) == 90
    assert litter_level_percent_from_mm(459, full_mm=450) == 75


def test_two_point_calibration_needs_no_assumed_slope() -> None:
    assert litter_level_percent_from_mm(520, full_mm=453, empty_mm=520) == 0
    assert litter_level_percent_from_mm(453, full_mm=453, empty_mm=520) == 100
    assert litter_level_percent_from_mm(486, full_mm=453, empty_mm=520) == 51


def test_calibrated_percent_is_clamped() -> None:
    assert litter_level_percent_from_mm(300, full_mm=453) == 100
    assert litter_level_percent_from_mm(900, full_mm=453) == 0
    assert litter_level_percent_from_mm(900, full_mm=453, empty_mm=520) == 0


def test_a_nonsense_empty_reference_falls_back_to_one_point() -> None:
    # Empty is a LONGER distance than full; a swapped pair would otherwise
    # produce a negative span and nonsense output.
    assert litter_level_percent_from_mm(453, full_mm=453, empty_mm=400) == 90


def test_uncalibrated_behaviour_is_unchanged() -> None:
    assert litter_level_percent_from_mm(460) == litter_level_percent_from_mm(460, full_mm=None)


def test_uncalibrated_percent_cannot_exceed_full() -> None:
    # A well-filled globe reads a short distance, which the uncalibrated curve
    # happily extrapolated past 100.
    assert litter_level_percent_from_mm(428) == 100
    assert litter_level_percent_from_mm(300) == 100


def test_a_schedule_is_only_verified_when_every_day_agrees() -> None:
    """0x1B mirrors today alone, so it cannot stand in for the other six days.

    A dropped write to one weekday register would otherwise pass verification and
    leave the robot on a schedule the user never asked for.
    """
    days = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
    assert every_weekday_is(dict.fromkeys(days, 440), 440)
    assert not every_weekday_is({**dict.fromkeys(days, 440), "friday": 920}, 440)
    # Six of seven present: the missing day was never confirmed, so neither is this.
    assert not every_weekday_is(dict.fromkeys(days[:6], 440), 440)
    assert not every_weekday_is({}, 440)


def test_the_per_day_schedule_decodes_from_the_state_document() -> None:
    state = LitterRobot4State.from_state_doc(
        {"sleepTimeSunday": 440, "wakeTimeSunday": 920, "sleepTimeMonday": 450}
    )
    assert state.weekday_sleep_times == {"sunday": 440, "monday": 450}
    assert state.weekday_wake_times == {"sunday": 920}


def test_the_globe_moves_in_more_states_than_the_clean_cycle() -> None:
    """Any state where the ToF is not facing a level bed must suppress litter.

    13 is the automatic cycle the robot runs on power-up and 14 is the filter
    wizard, which parks the globe inverted for minutes. Both were unmapped, so
    both published ToF readings taken off a moving or upturned globe as though
    they were real litter levels.
    """
    for status in (10, 13, 14):
        state = LitterRobot4State.from_state_doc({"robotStatus": status, "litterLevel": 450})
        assert state.litter_level_mm is None, f"robotStatus {status} must suppress litter"
    ready = LitterRobot4State.from_state_doc({"robotStatus": 4, "litterLevel": 450})
    assert ready.litter_level_mm == 450


def test_the_weekday_sleep_field_is_a_day_bitmask() -> None:
    """0x1D names WHICH days, not whether.

    The panel's own 8-hour sleep writes 0x7F — all seven bits — which is how the
    shape surfaced. Decoding it as a boolean loses the days, and writing 1 for
    "on" arms Sunday alone: a switch that appears to work when tested on a Sunday
    and silently does nothing the rest of the week.
    """
    weekend = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": 0x41})
    assert weekend.weekday_sleep_enabled
    assert weekend.weekday_sleep_days == frozenset({"sunday", "saturday"})

    off = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": 0})
    assert off.weekday_sleep_enabled is False
    assert off.weekday_sleep_days == frozenset()


def test_a_stale_single_day_does_not_confirm_an_all_days_write() -> None:
    """Verifying "any bit set" would accept a mask the write never produced.

    A register left at 0x01 by the old implementation already reads as enabled,
    so a dropped all-days write would report success with six days unarmed.
    """
    from whiskerless.devices.litter_robot_4.models import weekday_sleep_days_match

    stale = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": 0x01})
    assert stale.weekday_sleep_enabled          # the weak predicate is satisfied
    assert not weekday_sleep_days_match(stale, True)

    landed = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": 0x7F})
    assert weekday_sleep_days_match(landed, True)
    off = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": 0})
    assert weekday_sleep_days_match(off, False)

    # A document that never carried the register verifies nothing in either
    # direction: unread is not the same as clear.
    unseen = LitterRobot4State.from_state_doc({})
    assert not weekday_sleep_days_match(unseen, True)
    assert not weekday_sleep_days_match(unseen, False)


def test_a_cloud_style_weekday_flag_still_decodes() -> None:
    """Cloud-connected robots report this field as a bool or a "true"/"false" string.

    The numeric mask path rejects both, so reading it only as an int would report
    the schedule as unknown on exactly the robots that phrase it that way.
    """
    for raw in (True, "true"):
        assert LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": raw}).weekday_sleep_enabled
    for raw in (False, "false"):
        state = LitterRobot4State.from_state_doc({"weekdaySleepModeEnabled": raw})
        assert state.weekday_sleep_enabled is False

def test_filter_wizard_status_decodes_and_suppresses_litter() -> None:
    """robotStatus 14 = the filter-change wizard (owner-narrated chord, 1.4.4).

    Held for the wizard's whole life: park rotation, the indefinite wait, and
    the Reset-triggered return. It is not a clean cycle, and the globe parks
    inverted, so litter readings must be suppressed.
    """
    state = LitterRobot4State.from_state_doc({"robotStatus": 14, "litterLevel": 575})
    assert state.robot_status == "changing_filter"
    assert state.is_cleaning is False
    assert state.litter_level is None
    assert state.litter_level_mm is None


def test_filter_wizard_cycle_phases_decode() -> None:
    # Live ladder from the narrated chord: 14 rotating to the park, 15 parked
    # waiting; the return leg reuses the normal 4/5 rails.
    park = LitterRobot4State.from_state_doc({"robotCycleStatus": 14})
    wait = LitterRobot4State.from_state_doc({"robotCycleStatus": 15})
    assert park.robot_cycle_status == "filter_park"
    assert wait.robot_cycle_status == "filter_wait"
    # Neither phase may imply an active clean cycle.
    assert park.is_cleaning is False
    assert wait.is_cleaning is False


def test_an_unparsable_number_is_none_rather_than_zero() -> None:
    """A zero would be published as a real reading; unknown is the honest answer."""
    state = LitterRobot4State.from_state_doc({"catWeight": "not a number", "litterLevel": None})
    assert state.cat_weight is None


@pytest.mark.parametrize("text", ["0", "false", "off", "no", "wake", "none"])
def test_the_falsy_spellings_the_firmware_uses_all_decode(text: str) -> None:
    """'wake' is the panel-sleep register's way of saying off, not a separate state."""
    assert LitterRobot4State.from_state_doc({"isKeypadLockout": text}).keypad_lockout is False


def test_a_bool_is_not_mistaken_for_an_enum_index() -> None:
    """True would otherwise index the map as 1 and name a state the robot never sent."""
    assert LitterRobot4State.from_state_doc({"nightLightMode": True}).night_light_mode is None


def test_an_unmappable_string_is_returned_as_itself() -> None:
    """A cloud spelling we have not seen is more useful raw than dropped."""
    state = LitterRobot4State.from_state_doc({"robotStatus": "ROBOT_SOMETHING_NEW"})
    assert state.robot_status_raw == "ROBOT_SOMETHING_NEW"


def test_cat_detect_bit0_reads_the_bit_and_refuses_strings() -> None:
    """Bit 0 tracked the cat on both observed vocabularies; bit 1 did not."""
    from whiskerless.devices.litter_robot_4.models import cat_detect_bit0

    assert cat_detect_bit0(0) is False
    assert cat_detect_bit0(1) is True
    assert cat_detect_bit0(2) is False
    assert cat_detect_bit0(3) is True
    assert cat_detect_bit0("3") is True
    assert cat_detect_bit0("CAT_DETECT") is None
    assert cat_detect_bit0(None) is None
