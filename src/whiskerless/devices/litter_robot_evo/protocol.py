"""Parse inbound Litter-Robot EVO MQTT messages into typed messages.

The EVO publishes three kinds of message, none of them a state document:

* **activity** — ``{"type": "activity", "data": ["0xBBRRVVVV", ...]}``: telemetry
  and write echoes. A read reply has ``"type": "query"`` and one element per
  register read, in request order, each carrying the register's current value
  (or 0 for a register that cannot be read; see ``const.READABLE_REGISTERS``).
* **event** — ``{"type": "cycle" | "usage", "uuid": …, "data": [...]}`` on
  ``…/event``: a completed cycle or a weight event.
* **pawprint** — ``{"type": "pawprint", "data": [{"type": …, …}]}``: typed JSON,
  such as the ``pet_profile_request`` the robot sends after power-on and the
  ``pet_id_match`` it sends when it identifies a pet by weight.

Messages on ``…/command`` (our own publishes, or the cloud's) are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .codec import ActivityReading, decode_activity_code, encode_command_payload

__all__ = [
    "PET_ID_MATCH",
    "PET_PROFILE_REQUEST",
    "ActivityMessage",
    "EventMessage",
    "PawprintMessage",
    "PetIdMatch",
    "build_command_payload",
    "parse_message",
]

#: The `pawprint` message the robot sends after power-on, asking for the account's pets.
PET_PROFILE_REQUEST = "pet_profile_request"
#: The `pawprint` message the robot sends when it matches a weight to one of the pet
#: profiles the cloud sent it.
PET_ID_MATCH = "pet_id_match"


@dataclass(frozen=True, slots=True)
class PetIdMatch:
    """The pet the robot identified: the matched profile id and the robot's confidence."""

    profile: str
    confidence: float | None = None
    #: What the robot based the match on, passed through as sent.
    sources: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ActivityMessage:
    """Telemetry, write echoes, or (with ``query``) a read reply."""

    readings: list[ActivityReading] = field(default_factory=list)
    #: A read reply. Its values are always 0, so it must not update state.
    query: bool = False
    raw: Any = None


@dataclass(frozen=True, slots=True)
class EventMessage:
    """A record from ``…/event``: ``cycle`` when a cycle completes, ``usage`` for weight events."""

    event_type: str
    uuid: str | None = None
    readings: list[ActivityReading] = field(default_factory=list)
    raw: Any = None


@dataclass(frozen=True, slots=True)
class PawprintMessage:
    """A typed JSON message in the ``pawprint`` envelope."""

    message_type: str
    body: dict[str, Any] = field(default_factory=dict)
    uuid: str | None = None
    raw: Any = None

    @property
    def pet_id_match(self) -> PetIdMatch | None:
        """The identified pet, when this is a ``pet_id_match`` message with a profile."""
        if self.message_type != PET_ID_MATCH:
            return None
        profile = self.body.get("profile")
        if not isinstance(profile, str):
            return None
        confidence = self.body.get("confidence")
        sources = self.body.get("sources")
        return PetIdMatch(
            profile=profile,
            confidence=float(confidence)
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            else None,
            sources=tuple(sources) if isinstance(sources, list) else (),
        )


def build_command_payload(serial: str, *codes: str) -> str:
    """Serialize command code(s) into the ``…/command`` JSON payload."""
    return encode_command_payload(serial, list(codes))


def parse_message(
    topic: str, payload: bytes | bytearray | str
) -> ActivityMessage | EventMessage | PawprintMessage | None:
    """Decode an inbound MQTT message, or ``None`` if it is not a robot message."""
    if topic.endswith("/command"):
        return None

    text = (
        payload.decode("utf-8", "replace")
        if isinstance(payload, (bytes, bytearray))
        else payload
    )
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None

    kind = body.get("type")
    data = body.get("data")
    uuid = body.get("uuid") if isinstance(body.get("uuid"), str) else None

    if kind == "pawprint":
        inner = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        inner_type = inner.get("type")
        return PawprintMessage(
            message_type=inner_type if isinstance(inner_type, str) else "",
            body=inner,
            uuid=uuid,
            raw=body,
        )

    if not isinstance(data, list):
        return None
    readings = _readings(data)
    if topic.endswith("/event"):
        return EventMessage(
            event_type=kind if isinstance(kind, str) else "",
            uuid=uuid,
            readings=readings,
            raw=body,
        )
    return ActivityMessage(readings=readings, query=kind == "query", raw=body)


def _readings(data: list[Any]) -> list[ActivityReading]:
    readings: list[ActivityReading] = []
    for code in data:
        if not isinstance(code, str):
            continue
        try:
            readings.append(decode_activity_code(code))
        except Exception:  # noqa: BLE001 — one bad element must not drop the whole message
            continue
    return readings
