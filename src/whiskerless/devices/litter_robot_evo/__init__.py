"""Litter-Robot EVO local protocol: codec, command catalog, state model, link."""

from __future__ import annotations

from . import commands, const, models, protocol
from .codec import (
    ActivityReading,
    decode_activity_code,
    encode_command_payload,
    encode_read,
    encode_write,
)
from .commands import Command
from .link import LitterRobotEvoLink
from .models import LitterRobotEvoState, apply_message
from .protocol import (
    PET_ID_MATCH,
    PET_PROFILE_REQUEST,
    ActivityMessage,
    EventMessage,
    PawprintMessage,
    PetIdMatch,
    build_command_payload,
    parse_message,
)

__all__ = [
    "PET_ID_MATCH",
    "PET_PROFILE_REQUEST",
    "ActivityMessage",
    "ActivityReading",
    "Command",
    "EventMessage",
    "LitterRobotEvoLink",
    "LitterRobotEvoState",
    "PawprintMessage",
    "PetIdMatch",
    "apply_message",
    "build_command_payload",
    "commands",
    "const",
    "decode_activity_code",
    "encode_command_payload",
    "encode_read",
    "encode_write",
    "models",
    "parse_message",
    "protocol",
]
