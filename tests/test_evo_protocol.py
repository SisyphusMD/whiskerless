"""Parsing the EVO's three message kinds. Every payload here is synthetic."""

from __future__ import annotations

import json

import pytest

from whiskerless.devices.litter_robot_evo.protocol import (
    PET_ID_MATCH,
    PET_PROFILE_REQUEST,
    ActivityMessage,
    EventMessage,
    PawprintMessage,
    PetIdMatch,
    build_command_payload,
    parse_message,
)

PREFIX = "prod/robots/LRE-01-40-01-2610-000000"


def test_activity_decodes_every_element() -> None:
    body = {"timestamp": "2026-01-01T00:00:00Z", "type": "activity", "data": ["0x01200001", "0x01020006"]}
    message = parse_message(f"{PREFIX}/activity", json.dumps(body).encode())
    assert isinstance(message, ActivityMessage)
    assert not message.query
    assert [r.address for r in message.readings] == [(0x01, 0x20), (0x01, 0x02)]


def test_a_read_reply_is_marked_as_a_query() -> None:
    body = {"type": "query", "data": ["0x010E0000"]}
    message = parse_message(f"{PREFIX}/activity", json.dumps(body))
    assert isinstance(message, ActivityMessage)
    assert message.query


def test_a_bad_element_does_not_drop_the_rest() -> None:
    body = {"type": "activity", "data": ["0xZZ", 5, "0x01140001"]}
    message = parse_message(f"{PREFIX}/activity", json.dumps(body))
    assert isinstance(message, ActivityMessage)
    assert [r.hex for r in message.readings] == ["0x01140001"]


def test_an_event_record_carries_its_type_uuid_and_readings() -> None:
    body = {"type": "cycle", "uuid": "00000000-0000-0000-0000-000000000000", "data": ["0x01030004", "0x050A000F"]}
    message = parse_message(f"{PREFIX}/event", json.dumps(body))
    assert isinstance(message, EventMessage)
    assert message.event_type == "cycle"
    assert message.uuid == "00000000-0000-0000-0000-000000000000"
    assert len(message.readings) == 2


def test_an_event_without_a_string_type_still_parses() -> None:
    message = parse_message(f"{PREFIX}/event", json.dumps({"type": 3, "data": []}))
    assert isinstance(message, EventMessage)
    assert message.event_type == ""
    assert message.uuid is None


def test_a_pawprint_message_exposes_its_inner_type() -> None:
    body = {"type": "pawprint", "uuid": "u", "data": [{"type": PET_PROFILE_REQUEST}]}
    message = parse_message(f"{PREFIX}/activity", json.dumps(body))
    assert isinstance(message, PawprintMessage)
    assert message.message_type == PET_PROFILE_REQUEST
    assert message.uuid == "u"


def test_a_pawprint_message_without_a_body_is_still_a_pawprint() -> None:
    message = parse_message(f"{PREFIX}/activity", json.dumps({"type": "pawprint", "data": []}))
    assert isinstance(message, PawprintMessage)
    assert message.message_type == ""
    assert message.body == {}


def test_commands_are_ignored() -> None:
    assert parse_message(f"{PREFIX}/command", json.dumps({"data": ["0x0202010808"]})) is None


def test_anything_that_is_not_a_robot_message_is_none() -> None:
    assert parse_message(f"{PREFIX}/activity", "not json") is None
    assert parse_message(f"{PREFIX}/activity", "[1, 2]") is None
    assert parse_message(f"{PREFIX}/activity", json.dumps({"type": "activity"})) is None


def test_the_command_payload_lists_every_code() -> None:
    payload = json.loads(build_command_payload("LRE-01-40-01-2610-000000", "0x020103000A"))
    assert payload["data"] == ["0x020103000A"]


def test_a_pet_id_match_is_parsed() -> None:
    """The profile id is invented."""
    body = {
        "type": "pawprint",
        "data": [{"type": PET_ID_MATCH, "profile": "PET-00000000-0000-0000-0000-000000000000",
                  "confidence": 1, "sources": ["weight", {"kind": "history"}]}],
    }
    message = parse_message(f"{PREFIX}/activity", json.dumps(body))
    assert isinstance(message, PawprintMessage)
    match = message.pet_id_match
    assert match == PetIdMatch(
        profile="PET-00000000-0000-0000-0000-000000000000",
        confidence=1.0,
        sources=("weight", {"kind": "history"}),
    )


@pytest.mark.parametrize(
    "inner",
    [
        {"type": PET_PROFILE_REQUEST},
        {"type": PET_ID_MATCH},
        {"type": PET_ID_MATCH, "profile": 7},
    ],
)
def test_no_pet_id_match_without_a_profile(inner: dict[str, object]) -> None:
    message = parse_message(f"{PREFIX}/activity", json.dumps({"type": "pawprint", "data": [inner]}))
    assert isinstance(message, PawprintMessage)
    assert message.pet_id_match is None


def test_a_pet_id_match_without_confidence_or_sources_keeps_the_profile() -> None:
    body = {"type": "pawprint", "data": [{"type": PET_ID_MATCH, "profile": "PET-x", "confidence": True}]}
    message = parse_message(f"{PREFIX}/activity", json.dumps(body))
    assert isinstance(message, PawprintMessage)
    assert message.pet_id_match == PetIdMatch(profile="PET-x")
