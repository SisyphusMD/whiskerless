"""State accumulated from telemetry and echoes. All readings are synthetic."""

from __future__ import annotations

from whiskerless.devices.litter_robot_evo.codec import decode_activity_code
from whiskerless.devices.litter_robot_evo.models import LitterRobotEvoState, apply_message
from whiskerless.devices.litter_robot_evo.protocol import (
    ActivityMessage,
    EventMessage,
    PawprintMessage,
)


def _activity(*codes: str, query: bool = False) -> ActivityMessage:
    return ActivityMessage(readings=[decode_activity_code(c) for c in codes], query=query)


def test_everything_is_unknown_until_reported() -> None:
    state = LitterRobotEvoState()
    assert state.robot_status is None
    assert state.is_cleaning is None
    assert state.sleep_mask is None


def test_hardware_and_status_telemetry_is_decoded() -> None:
    state = apply_message(
        LitterRobotEvoState(),
        _activity(
            "0x0103000A", "0x01020014", "0x01010201", "0x010A0003", "0x010B0002",
            "0x01140001", "0x01180001", "0x01200000",
        ),
    )
    assert state.robot_status == "cleaning"
    assert state.is_cleaning is True
    assert state.display == "cycling"
    assert state.last_button == 0x0201
    assert (state.cycle_step, state.cycle_phase) == (3, 2)
    assert state.power_on is True
    assert state.bonnet_removed is True
    assert state.drawer_removed is False


def test_an_unknown_status_keeps_its_raw_value() -> None:
    state = apply_message(LitterRobotEvoState(), _activity("0x01030063", "0x010200FE"))
    assert state.robot_status is None
    assert state.robot_status_raw == 0x63
    assert state.display is None
    assert state.display_raw == 0xFE
    assert state.is_cleaning is False


def test_settings_echoes_are_decoded() -> None:
    state = apply_message(
        LitterRobotEvoState(),
        _activity("0x02010801", "0x02090007", "0x020A0001", "0x02100041", "0x02110000", "0x021202D0"),
    )
    assert (state.screen_brightness, state.led_brightness) == (8, 1)
    assert state.cycle_delay_minutes == 7
    assert state.keypad_lockout is True
    assert state.sleep_mask == 0x41
    assert state.sleep_days == frozenset({"sunday", "saturday"})
    assert state.sleep_times == {"sunday": 0}
    assert state.wake_times == {"sunday": 720}


def test_sensor_and_measurement_readings_are_decoded() -> None:
    state = apply_message(
        LitterRobotEvoState(), _activity("0x051BFFD6", "0x050A000F", "0x08120001", "0x05990001")
    )
    assert state.weight_raw == -42
    assert state.drawer_counter == 15
    assert state.weight_settling is True
    assert state.registers[(0x05, 0x99)] == 1


def test_undecoded_addresses_are_kept_raw() -> None:
    state = apply_message(LitterRobotEvoState(), _activity("0x01990005", "0x02990001", "0x09010001"))
    assert state.registers[(0x01, 0x99)] == 5
    assert state.registers[(0x02, 0x99)] == 1
    assert state.registers[(0x09, 0x01)] == 1


def test_a_multi_element_read_reply_folds_every_element() -> None:
    """Synthetic: the reply to one message reading five registers."""
    reply = _activity("0x01030004", "0x02090007", "0x01050009", "0x02010808", "0x01140001", query=True)
    state = apply_message(LitterRobotEvoState(), reply)
    assert state.robot_status == "ready"
    assert state.cycle_delay_minutes == 7
    assert state.odometer_power_cycles == 9
    assert (state.screen_brightness, state.led_brightness) == (8, 8)
    assert state.power_on is True


def test_a_read_reply_for_an_unreadable_register_never_overwrites_telemetry() -> None:
    """The display code answers a read with 0 whatever it shows."""
    state = apply_message(LitterRobotEvoState(), _activity("0x01020016"))
    after = apply_message(state, _activity("0x01020000", "0x02090007", query=True))
    assert after.display == "idle"
    assert after.cycle_delay_minutes == 7
    assert apply_message(state, _activity("0x01020000", query=True)) is state


def test_the_main_board_id_is_read_from_bank_09() -> None:
    state = apply_message(LitterRobotEvoState(), _activity("0x09082904", query=True))
    assert state.main_board_id == 0x2904


def test_event_records_update_state() -> None:
    event = EventMessage(event_type="cycle", readings=[decode_activity_code("0x01030004")])
    assert apply_message(LitterRobotEvoState(), event).robot_status == "ready"


def test_a_pawprint_message_changes_nothing() -> None:
    state = LitterRobotEvoState()
    assert apply_message(state, PawprintMessage(message_type="pet_profile_request")) is state


def test_applying_readings_never_mutates_the_previous_state() -> None:
    before = apply_message(LitterRobotEvoState(), _activity("0x02110000"))
    apply_message(before, _activity("0x02130010"))
    assert before.sleep_times == {"sunday": 0}


def test_an_empty_cycle_and_the_odometers_are_decoded() -> None:
    state = apply_message(
        LitterRobotEvoState(),
        _activity("0x0103000B", "0x01010202", "0x01070002", "0x010A0006", "0x01050009"),
    )
    assert state.robot_status == "emptying"
    assert state.is_emptying is True
    assert state.is_cleaning is False
    assert state.last_button == 0x0202
    assert state.odometer_empty_cycles == 2
    assert state.odometer_power_cycles == 9
    assert state.cycle_step == 6


def test_emptying_is_unknown_until_the_status_is_reported() -> None:
    assert LitterRobotEvoState().is_emptying is None


def test_repeated_telemetry_folds_to_the_same_state() -> None:
    """Around a power change the robot repeats readings two or three times in a row."""
    once = apply_message(LitterRobotEvoState(), _activity("0x01140001", "0x01050008", "0x01030002"))
    repeated = once
    for _ in range(3):
        repeated = apply_message(repeated, _activity("0x01140001", "0x01050008", "0x01030002"))
    assert repeated == once


def test_a_usage_event_carries_the_weight_in_hundredths_of_a_pound() -> None:
    event = EventMessage(
        event_type="usage",
        readings=[decode_activity_code(c) for c in ("0x01030004", "0x03050030", "0x03060373")],
    )
    state = apply_message(LitterRobotEvoState(), event)
    assert state.last_weight_lb == 8.83
    assert state.registers[(0x03, 0x05)] == 0x30


def test_a_pet_id_match_records_the_pet() -> None:
    """The profile id is invented."""
    message = PawprintMessage(
        message_type="pet_id_match",
        body={"type": "pet_id_match", "profile": "PET-00000000-0000-0000-0000-000000000000",
              "confidence": 0.97, "sources": ["weight"]},
    )
    state = apply_message(LitterRobotEvoState(), message)
    assert state.last_pet_profile == "PET-00000000-0000-0000-0000-000000000000"
    assert state.last_pet_confidence == 0.97
