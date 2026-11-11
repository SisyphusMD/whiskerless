"""Litter-Robot EVO wire codec — encode commands, decode telemetry elements.

Wire grammar (PROVEN). A command payload published to ``…/command`` is JSON::

    {"serial": "LRE-…", "data": ["0xTTBBRRVVVV", ...]}

Each ``data`` element is the literal ``"0x"`` plus exactly 10 hex digits:

    TT    01 = read, 02 = write
    BB    bank
    RR    register within the bank
    VVVV  16-bit value, big-endian

Telemetry, write echoes and read replies drop the type byte: ``0xBBRRVVVV``.

The LR4's 8-digit elements are not ignored by the EVO: it parses them in this
layout, acknowledges the wrong address and acts on nothing. Everything here
therefore insists on the full width in both directions.
"""

from __future__ import annotations

import dataclasses
import json
import string
from dataclasses import dataclass

from ...exceptions import ProtocolError

__all__ = [
    "ActivityReading",
    "decode_activity_code",
    "encode_command_payload",
    "encode_read",
    "encode_write",
]


def encode_read(bank: int, register: int) -> str:
    """Build a read of ``bank``/``register`` (``0x01BBRR0000``).

    The robot answers on activity with ``"type": "query"`` and ``0xBBRRVVVV``
    carrying the register's current value; a register outside
    ``const.READABLE_REGISTERS`` answers with 0 whatever it holds.
    """
    _check_byte(bank, "bank")
    _check_byte(register, "register")
    return f"0x01{bank:02X}{register:02X}0000"


def encode_write(bank: int, register: int, value: int) -> str:
    """Build a write of ``bank``/``register`` = ``value`` (``0x02BBRRVVVV``)."""
    _check_byte(bank, "bank")
    _check_byte(register, "register")
    if not 0 <= value <= 0xFFFF:
        raise ProtocolError(f"value {value} out of 16-bit range")
    return f"0x02{bank:02X}{register:02X}{value:04X}"


def encode_command_payload(serial: str, codes: list[str]) -> str:
    """Serialize one or more command codes into the ``…/command`` JSON payload."""
    return json.dumps({"serial": serial, "data": list(codes)})


@dataclass(frozen=True, slots=True)
class ActivityReading:
    """A single decoded ``0xBBRRVVVV`` element."""

    bank: int
    register: int
    value: int
    #: Exactly what the robot sent; excluded from equality like the LR4 reading.
    source: str = dataclasses.field(default="", compare=False)

    @property
    def address(self) -> tuple[int, int]:
        """``(bank, register)``, the key state is tracked by."""
        return (self.bank, self.register)

    @property
    def signed_value(self) -> int:
        """The value as a signed 16-bit integer (the weight sensor is signed)."""
        return self.value - 0x10000 if self.value & 0x8000 else self.value

    @property
    def hex(self) -> str:
        return self.source or f"0x{self.bank:02X}{self.register:02X}{self.value:04X}"


def decode_activity_code(code: str) -> ActivityReading:
    """Decode a ``0xBBRRVVVV`` telemetry / echo / read-reply element."""
    raw = code.strip()
    if len(raw) != 10 or raw[:2].lower() != "0x":
        raise ProtocolError(f"telemetry element must be '0x' + 8 hex digits (got {code!r})")
    if not all(character in string.hexdigits for character in raw[2:]):
        raise ProtocolError(f"non-hex telemetry element {code!r}")
    packed = int(raw[2:], 16)
    return ActivityReading(
        bank=(packed >> 24) & 0xFF,
        register=(packed >> 16) & 0xFF,
        value=packed & 0xFFFF,
        source=raw,
    )


def _check_byte(value: int, name: str) -> None:
    if not 0 <= value <= 0xFF:
        raise ProtocolError(f"{name} {value} out of byte range 0x00–0xFF")
