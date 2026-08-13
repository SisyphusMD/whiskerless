"""Litter-Robot 4 local protocol: codec, command catalog, state model, link."""

from __future__ import annotations

from . import commands, const
from .codec import (
    ActivityReading,
    decode_activity_code,
    encode_command_payload,
    encode_read,
    encode_write,
)
from .commands import Command
from .events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayMoved,
    GlobeMotorFaultChanged,
    HopperDispensed,
    HopperLinkChanged,
    LitterRobotEvent,
    events_from_readings,
)
from .link import LitterRobot4Link
from .models import (
    LitterRobot4State,
    every_weekday_is,
    litter_level_percent_from_mm,
    weekday_sleep_days_match,
)
from .protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)

__all__ = [
    "ActivityMessage",
    "ActivityReading",
    "CatVisitEnded",
    "CatWeightMeasured",
    "Command",
    "DrawerBayMoved",
    "GlobeMotorFaultChanged",
    "HopperDispensed",
    "HopperLinkChanged",
    "LitterRobot4Link",
    "LitterRobot4State",
    "LitterRobotEvent",
    "StateMessage",
    "build_command_payload",
    "commands",
    "const",
    "decode_activity_code",
    "encode_command_payload",
    "encode_read",
    "encode_write",
    "events_from_readings",
    "every_weekday_is",
    "litter_level_percent_from_mm",
    "parse_message",
    "weekday_sleep_days_match",
]
