"""Litter-Robot 4 local protocol: codec, command catalog, state model, link."""

from __future__ import annotations

from . import commands, const
from .client import LitterRobot4Client
from .codec import (
    ActivityReading,
    decode_activity_code,
    encode_command_payload,
    encode_read,
    encode_write,
)
from .commands import Command
from .link import LitterRobot4Link
from .models import LitterRobot4State, litter_level_percent_from_mm
from .protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)

__all__ = [
    "ActivityMessage",
    "ActivityReading",
    "Command",
    "LitterRobot4Client",
    "LitterRobot4Link",
    "LitterRobot4State",
    "StateMessage",
    "build_command_payload",
    "commands",
    "const",
    "decode_activity_code",
    "encode_command_payload",
    "encode_read",
    "encode_write",
    "litter_level_percent_from_mm",
    "parse_message",
]
