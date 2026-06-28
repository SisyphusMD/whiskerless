"""Litter-Robot 4 wire codec — encode commands, decode activity codes.

Wire grammar (PROVEN). A command payload published to ``…/command`` is JSON::

    {"serial": "LR4Cxxxxxx", "data": ["0xTTRRVVVV", ...]}

Each ``data`` element is the literal ``"0x"`` plus exactly 8 hex digits:

    char [3]   T   1 = register READ, 2 = macro / generic register WRITE
    char [4:6] RR  register / opcode byte (0x00–0xFF)
    char [6:8] HH  value high byte
    char [8:10] LL value low byte → 16-bit value (HH << 8) | LL

Elements that are not exactly 10 chars are silently dropped by the firmware, so
this module always emits the full width. The ``…/activity`` stream and type-1
read echoes use a shorter ``0xRRVVVV`` form (register + 16-bit value, no type).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...exceptions import ProtocolError


def encode_read(register: int) -> str:
    """Build a type-1 READ of ``register`` (``0x01RR0000``)."""
    _check_byte(register, "register")
    return f"0x01{register:02X}0000"


def encode_write(register: int, value: int) -> str:
    """Build a type-2 WRITE of ``register`` = ``value`` (``0x02RRVVVV``).

    ``value`` is the full 16-bit value: for 8-bit settings pass 0–255 (it lands
    in the low byte with a zero high byte); for packed/16-bit values pass the
    composed ``(HH << 8) | LL``.
    """
    _check_byte(register, "register")
    if not 0 <= value <= 0xFFFF:
        raise ProtocolError(f"value {value} out of 16-bit range")
    return f"0x02{register:02X}{value:04X}"


def encode_command_payload(serial: str, codes: list[str]) -> str:
    """Serialize one or more command codes into the ``…/command`` JSON payload."""
    return json.dumps({"serial": serial, "data": list(codes)})


@dataclass(frozen=True, slots=True)
class ActivityReading:
    """A single decoded ``0xRRVVVV`` element from the activity stream."""

    register: int
    value: int

    @property
    def hex(self) -> str:
        return f"0x{self.register:02X}{self.value:04X}"


def decode_activity_code(code: str) -> ActivityReading:
    """Decode a ``0xRRVVVV`` activity / read-echo element.

    The register is the high byte above the 16-bit value, so this also tolerates
    the occasional wider element by masking.
    """
    raw = code.strip()
    if raw[:2].lower() != "0x":
        raise ProtocolError(f"activity code must start with 0x (got {code!r})")
    try:
        packed = int(raw, 16)
    except ValueError as exc:
        raise ProtocolError(f"non-hex activity code {code!r}") from exc
    return ActivityReading(register=(packed >> 16) & 0xFF, value=packed & 0xFFFF)


def _check_byte(value: int, name: str) -> None:
    if not 0 <= value <= 0xFF:
        raise ProtocolError(f"{name} {value} out of byte range 0x00–0xFF")
