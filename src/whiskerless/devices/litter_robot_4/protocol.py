"""Parse inbound Litter-Robot 4 MQTT messages into typed events.

Two kinds of message arrive on ``…/state`` and ``…/activity``:

* **state** — a full named JSON document (decoded into :class:`LitterRobot4State`)
* **activity** — ``{"data": ["0xRRVVVV", ...]}`` telemetry / action echoes

Our own command publishes echo back on ``…/command``; those are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .codec import ActivityReading, decode_activity_code, encode_command_payload
from .const import activity_topic, command_topic, state_topic, subscribe_topic
from .models import LitterRobot4State

__all__ = [
    "ActivityMessage",
    "StateMessage",
    "activity_topic",
    "build_command_payload",
    "command_topic",
    "parse_message",
    "state_topic",
    "subscribe_topic",
]


@dataclass(frozen=True, slots=True)
class StateMessage:
    """A decoded full-state document."""

    state: LitterRobot4State
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ActivityMessage:
    """One or more decoded activity / read-echo readings."""

    readings: list[ActivityReading] = field(default_factory=list)
    raw: Any = None


def build_command_payload(serial: str, *codes: str) -> str:
    """Serialize command code(s) into the ``…/command`` JSON payload."""
    return encode_command_payload(serial, list(codes))


def parse_message(
    topic: str, payload: bytes | bytearray | str
) -> StateMessage | ActivityMessage | None:
    """Decode an inbound MQTT message, or ``None`` if it is not a robot event."""
    if topic.endswith("/command"):
        return None  # our own command echo

    text = (
        payload.decode("utf-8", "replace")
        if isinstance(payload, (bytes, bytearray))
        else payload
    )
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    is_state = topic.endswith("/state") or (isinstance(body, dict) and body.get("type") == "state")
    if isinstance(body, dict) and is_state:
        return StateMessage(state=LitterRobot4State.from_state_doc(body), raw=body)

    codes = body.get("data") if isinstance(body, dict) else None
    if isinstance(codes, list):
        readings: list[ActivityReading] = []
        for code in codes:
            if not isinstance(code, str):
                continue
            try:
                readings.append(decode_activity_code(code))
            except Exception:  # noqa: BLE001 — one bad element must not drop the whole message
                continue
        return ActivityMessage(readings=readings, raw=body)

    return None
