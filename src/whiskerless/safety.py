"""The central safety guard for every Litter-Robot command.

The reverse-engineering proved that a handful of opcodes are brick- or
reset-class, and that the firmware applies **no whitelist** to the generic
register write — any unrecognised opcode writes an arbitrary PIC register. So
this module is the one chokepoint every send path funnels through: the CLI, the
Home Assistant integration, and any future caller classify a command here and
:func:`assert_sendable` refuses the dangerous ones *before* the bytes can leave
the process.

The command grammar guarded here is the LR4 ESP wire format: a 10-character
string ``0xTTRRVVVV`` where the second hex digit ``T`` is the type (1=read,
2=write/macro), ``RR`` the register/opcode, and ``VVVV`` the 16-bit value.
"""

from __future__ import annotations

from enum import Enum

from .exceptions import DangerousCommandError, MotorCommandError, NeverSendError, ProtocolError

# --- the evidence-backed safety classes --------------------------------------

#: Brick- or reset-class opcodes. Refused unconditionally — no override exists.
#: 0xAC erases/writes main-board flash; 0xA4 stages a globe-motor-controller OTA
#: (a near-miss in testing — it bailed only because a magic register check
#: failed); 0xAD pulses the PIC reset line. All three can leave the robot dead.
NEVER_SEND_OPCODES: frozenset[int] = frozenset({0xA4, 0xAC, 0xAD})

#: Opcode that drives the globe motor (clean cycle). Allowed only with opt-in.
MOTOR_OPCODES: frozenset[int] = frozenset({0xA3})

#: Report macros that are safe to send with a zero value (PROVEN live). A
#: non-zero value on these indexes a firmware jump table, so it is treated as
#: dangerous instead.
SAFE_REPORT_MACROS: frozenset[int] = frozenset({0xA0, 0xA1, 0xA7, 0xA9, 0xAE})

#: Registers in the writable *settings* bank — the full set validated by a live
#: read-modify-restore sweep. Generic writes here are reversible and safe.
SAFE_SETTINGS_REGISTERS: frozenset[int] = frozenset(
    {0x05, 0x0E, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, *range(0x1E, 0x2C)}
)


class Hazard(Enum):
    """How dangerous a parsed command is."""

    NOOP = "noop"            # type byte is neither read nor write → silent no-op
    SAFE = "safe"            # read, report macro (value 0), or settings write
    MOTOR = "motor"          # drives the globe (clean cycle)
    DANGEROUS = "dangerous"  # untraced / control-band / calibration / identity write
    NEVER = "never"          # brick / reset-class — unconditionally refused


class CommandType(Enum):
    """The wire ``T`` nibble."""

    READ = 1
    WRITE = 2
    NOOP = 0  # any other value is a firmware no-op


def parse_code(code: str) -> tuple[CommandType, int, int]:
    """Parse a ``0xTTRRVVVV`` command string into ``(type, register, value)``.

    Raises :class:`ProtocolError` if the string is not a 10-character ``0x`` +
    8-hex-digit command element.
    """
    raw = code.strip()
    if len(raw) != 10 or raw[:2].lower() != "0x":
        raise ProtocolError(
            f"command must be '0x' + 8 hex digits (got {code!r}); "
            "8/6-digit elements are silently ignored by the firmware"
        )
    try:
        type_nibble = int(raw[3], 16)
        register = int(raw[4:6], 16)
        value = int(raw[6:10], 16)
    except ValueError as exc:
        raise ProtocolError(f"non-hex digits in command {code!r}") from exc

    try:
        ctype = CommandType(type_nibble)
    except ValueError:
        ctype = CommandType.NOOP
    return ctype, register, value


def classify(ctype: CommandType, register: int, value: int) -> Hazard:
    """Classify a parsed command into a :class:`Hazard`."""
    if ctype is CommandType.NOOP:
        return Hazard.NOOP
    if ctype is CommandType.READ:
        return Hazard.SAFE  # type-1 read builds a GET frame — structurally read-only

    # type-2: macro dispatch or generic register write.
    if register in NEVER_SEND_OPCODES:
        return Hazard.NEVER
    if register in MOTOR_OPCODES:
        return Hazard.MOTOR
    if register in SAFE_REPORT_MACROS:
        return Hazard.SAFE if value == 0 else Hazard.DANGEROUS
    if register in SAFE_SETTINGS_REGISTERS:
        return Hazard.SAFE
    # No firmware whitelist exists for the generic write — default to dangerous.
    return Hazard.DANGEROUS


def classify_code(code: str) -> Hazard:
    """Parse and classify a command string in one step."""
    return classify(*parse_code(code))


def assert_sendable(
    code: str,
    *,
    allow_motor: bool = False,
    allow_dangerous: bool = False,
) -> Hazard:
    """Raise unless ``code`` is allowed to be published to a robot.

    ``NEVER`` commands are refused unconditionally. ``MOTOR`` requires
    ``allow_motor=True`` (the caller must have confirmed the globe is clear), and
    ``DANGEROUS`` requires ``allow_dangerous=True``. Returns the
    :class:`Hazard` on success so callers can log/branch on it.
    """
    hazard = classify_code(code)
    if hazard is Hazard.NEVER:
        raise NeverSendError(
            f"{code} is a brick/reset-class command and is refused unconditionally"
        )
    if hazard is Hazard.MOTOR and not allow_motor:
        raise MotorCommandError(
            f"{code} drives the globe motor; pass allow_motor=True after "
            "confirming the globe is clear"
        )
    if hazard is Hazard.DANGEROUS and not allow_dangerous:
        raise DangerousCommandError(
            f"{code} is untraced/unverified (control-band, calibration, or "
            "unknown opcode); pass allow_dangerous=True to override"
        )
    return hazard
