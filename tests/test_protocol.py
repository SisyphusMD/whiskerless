"""Inbound message parsing: state docs, activity streams, and non-events."""

from __future__ import annotations

import json

from whiskerless.devices.litter_robot_4.protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)


def test_parse_state_document() -> None:
    raw = {"robotStatus": 4, "nightLightMode": 2, "DFILevelPercent": 80, "litterLevelPercentage": 55}
    message = parse_message("prod/LR4/LR4C000001/state", json.dumps(raw))
    assert isinstance(message, StateMessage)
    assert message.state.robot_status == "ready"
    assert message.state.night_light_mode == "auto"
    assert message.state.waste_drawer_level == 80
    assert message.state.litter_level == 55


def test_parse_state_by_type_field() -> None:
    raw = {"type": "state", "robotStatus": 13}
    message = parse_message("prod/LR4/LR4C000001/activity", json.dumps(raw))
    assert isinstance(message, StateMessage)
    assert message.state.is_cleaning is True


def test_parse_activity_stream() -> None:
    raw = {"data": ["0x09012C", "0x430052"]}
    message = parse_message("prod/LR4/LR4C000001/activity", json.dumps(raw))
    assert isinstance(message, ActivityMessage)
    assert {(r.register, r.value) for r in message.readings} == {(0x09, 0x012C), (0x43, 0x52)}


def test_activity_skips_bad_elements() -> None:
    message = parse_message("prod/LR4/x/activity", json.dumps({"data": ["0xZZ", "0x430000", 5]}))
    assert isinstance(message, ActivityMessage)
    assert [(r.register, r.value) for r in message.readings] == [(0x43, 0)]


def test_command_echo_ignored() -> None:
    assert parse_message("prod/LR4/x/command", json.dumps({"data": ["0x02A00000"]})) is None


def test_non_json_ignored() -> None:
    assert parse_message("prod/LR4/x/state", "not json") is None


def test_build_command_payload() -> None:
    assert json.loads(build_command_payload("S", "0x02A00000", "0x01470000")) == {
        "serial": "S",
        "data": ["0x02A00000", "0x01470000"],
    }
