"""Defensive state decoding — raw ints or cloud strings, partial payloads."""

from __future__ import annotations

import pytest

from whiskerless.devices.litter_robot_4.models import (
    LitterRobot4State,
    litter_level_percent_from_mm,
)


def test_enum_from_raw_int() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 13, "nightLightMode": 2})
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


def test_legacy_status_10_still_cat_detected() -> None:
    for doc in ({"robotStatus": 10}, {"robotStatus": 10, "espFirmware": "1.1.75"}):
        state = LitterRobot4State.from_state_doc(doc)
        assert state.robot_status == "cat_detected"
        assert state.is_cleaning is False


def test_esp14_new_status_values() -> None:
    cases = {5: "bonnet_removed", 6: "cat_sensor_timing", 7: "cat_sensor_timing", 25: "cat_detected"}
    for raw, slug in cases.items():
        assert LitterRobot4State.from_state_doc({"robotStatus": raw, **V14}).robot_status == slug


def test_unparsable_firmware_uses_legacy_map() -> None:
    state = LitterRobot4State.from_state_doc({"robotStatus": 10, "espFirmware": "weird"})
    assert state.robot_status == "cat_detected"


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
