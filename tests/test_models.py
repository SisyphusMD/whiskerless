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
