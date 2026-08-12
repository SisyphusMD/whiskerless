"""The central safety guard for every Litter-Robot command.

This module is the one chokepoint every send path funnels through: the CLI, the
Home Assistant integration, and any future caller classify a command here and
:func:`assert_sendable` refuses the dangerous ones *before* the bytes can leave
the process.

The never-send set is a **cost decision, not a proof**. One send of `0x02A30000` was
followed by `odometerPowerCycles` incrementing, which reads as a reboot — but that is
a single trial with no replication, on a unit that has since rebooted, dropped wifi
and latched a sensor unprompted. The macro range it sits in is described by a static
firmware brief as holding flash, OTA and reset operations, and that brief has since
been wrong about `0xA1`, `0x1A`-`0x1C` and `robotStatus`.

So the range is refused because there is nothing to gain by sending it — the cycle
and reset are both reachable through `0x01` — and a plausible main-board OTA on the
other side. Cheap insurance beats a confident story.

What is NOT claimed: that an unrecognised write reaches a PIC register directly.
That was asserted from the same brief and the robot contradicts it — writes to
`0x1A`, `0x1B` and `0x1C` are acknowledged and discarded, with the register
echoed unchanged, which is per-register handling, not a blind write path. What a
write to a register with *no* handler does is simply untested, and unknown
commands stay DANGEROUS because the cost of being wrong is asymmetric, not
because the mechanism is known.

The command grammar guarded here is the LR4 ESP wire format: a 10-character
string ``0xTTRRVVVV`` where the second hex digit ``T`` is the type (1=read,
2=write/macro), ``RR`` the register/opcode, and ``VVVV`` the 16-bit value.
"""

from __future__ import annotations

from enum import Enum

from .exceptions import DangerousCommandError, NeverSendError, ProtocolError

# --- the evidence-backed safety classes --------------------------------------

#: Brick- or reset-class opcodes. Refused unconditionally — no override exists.
#: A static firmware brief describes 0xAC as main-board flash, 0xA4 as a
#: globe-motor-controller OTA, and 0xAD as the PIC reset line; 0xA3 was long
#: mislabeled "cleanCycle" and one send was followed by a reboot, never replicated.
#: See the module docstring: this set is refused on cost, not on proof.
NEVER_SEND_OPCODES: frozenset[int] = frozenset({0xA3, 0xA4, 0xAC, 0xAD})

#: `0x01` carries panel button presses and accepts writes — writing the code the
#: robot emits for a button synthesises that press. Live-proven on ESP 1.1.75,
#: three trials, each echoing the register back with the documented signature.
#:
#: Classification is by VALUE, not register: the same register runs the globe or
#: acknowledges an alarm depending on which button is named.
#: Panel button bits, from Whisker's own control-panel documentation. Bit order
#: matches the physical left-to-right order of the buttons.
PANEL_BUTTON_POWER = 0x01
PANEL_BUTTON_CYCLE = 0x02
PANEL_BUTTON_RESET = 0x04
PANEL_BUTTON_EMPTY = 0x08
PANEL_BUTTON_CONNECT = 0x10
#: Low byte of the value: 0x01 short press, 0x02 long press. Buttons OR together,
#: so a combo is one write — which is how the documented multi-button functions
#: are expressed.
PANEL_PRESS_SHORT = 0x01
PANEL_PRESS_LONG = 0x02

PANEL_BUTTON_REGISTER: int = 0x01

#: Panel combos that destroy configuration or cut power. Refused unconditionally,
#: exactly like the flash/OTA opcodes, because the cost of sending one by accident
#: is a robot that needs BLE re-provisioning or a person to walk over to it.
#:
#: This is why `0x01` is whitelisted by VALUE rather than opened as a register:
#: FACTORY RESET sits two bits away from the clean cycle we ship. A fuzzer, a typo,
#: or a well-meaning "let's see what the other bits do" would wipe the broker
#: config that makes whiskerless work at all.
PANEL_BUTTON_NEVER: frozenset[int] = frozenset(
    {
        (PANEL_BUTTON_RESET | PANEL_BUTTON_EMPTY) << 8 | PANEL_PRESS_LONG,    # factory reset
        (PANEL_BUTTON_CONNECT) << 8 | PANEL_PRESS_LONG,                       # onboarding mode
        (PANEL_BUTTON_RESET | PANEL_BUTTON_CONNECT) << 8 | PANEL_PRESS_LONG,  # simulate plug pull
    }
)
#: Short presses of the buttons a person uses for routine operation. These are
#: SAFE and ungated: the write reproduces exactly the code the panel emits, so it
#: is the same event as someone pressing the button, and the firmware's pinch,
#: cat-detect and bonnet interlocks sit downstream and apply either way.
#:
#: An earlier version gated these behind a motor flag. That class was invented
#: when the globe trigger was believed to be an unknown macro opcode and the one
#: candidate turned out to reboot the robot. Once the trigger turned out to be a
#: synthesised button press the gate was guarding a hazard that does not exist,
#: and every caller passed the flag unconditionally, which made the real gates
#: below look like the same kind of formality.
#:
#: Empty rests on a weaker claim than the other two: its code is captured from a
#: physical press and has never been written. It shares the press type of both
#: proven writes and differs only in the button bit. It is not more *hazardous* —
#: it is a documented maintenance function with its own panel button — only less
#: proven, so it is labelled rather than gated. That it empties the globe into the
#: drawer is a reason not to wire it to an automation, not a reason to refuse it.
PANEL_BUTTON_SAFE: frozenset[int] = frozenset({0x0201, 0x0401, 0x0801})
#: Every other button value stays DANGEROUS. Power (0x0101) is captured and
#: deliberately left out: it toggles, so firing it can leave the robot switched
#: off and unreachable. That is the one panel button whose cost is losing control
#: of the device rather than moving litter around.
#:
#: Long presses cannot be synthesised at all — the firmware performs press type
#: 01 and silently declines 02 — so the hold-only chords never reach here.

#: Report macros that are safe to send with a zero value (PROVEN live). A
#: non-zero value on these indexes a firmware jump table, so it is treated as
#: dangerous instead.
SAFE_REPORT_MACROS: frozenset[int] = frozenset({0xA0, 0xA1, 0xA7, 0xA9, 0xAE})

#: Registers whose writes are safe. Most are reversible settings validated by a
#: live read-modify-restore sweep; 0x1A-0x1C are read-only views whose refused
#: writes are acknowledged and discarded.
SAFE_SETTINGS_REGISTERS: frozenset[int] = frozenset(
    {0x05, 0x0E, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, *range(0x1E, 0x2C)}
)


class Hazard(Enum):
    """How dangerous a parsed command is."""

    NOOP = "noop"            # type byte is neither read nor write → silent no-op
    SAFE = "safe"            # read, report macro (value 0), or settings write
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
    if register == PANEL_BUTTON_REGISTER:
        # By value: the same register runs the globe, acknowledges an alarm, or
        # factory-resets the robot depending only on which bits are set.
        if value in PANEL_BUTTON_NEVER:
            return Hazard.NEVER
        if value in PANEL_BUTTON_SAFE:
            return Hazard.SAFE
        return Hazard.DANGEROUS
    if register in SAFE_REPORT_MACROS:
        return Hazard.SAFE if value == 0 else Hazard.DANGEROUS
    if register in SAFE_SETTINGS_REGISTERS:
        return Hazard.SAFE
    # Untested, so refused by default: what the firmware does with a register it
    # has no handler for has never been observed either way.
    return Hazard.DANGEROUS


def classify_code(code: str) -> Hazard:
    """Parse and classify a command string in one step."""
    return classify(*parse_code(code))


def assert_sendable(code: str, *, allow_dangerous: bool = False) -> Hazard:
    """Raise unless ``code`` is allowed to be published to a robot.

    ``NEVER`` commands are refused unconditionally and ``DANGEROUS`` requires
    ``allow_dangerous=True``. Returns the :class:`Hazard` on success so callers
    can log or branch on it.
    """
    hazard = classify_code(code)
    if hazard is Hazard.NEVER:
        raise NeverSendError(
            f"{code} is a brick/reset-class command and is refused unconditionally"
        )
    if hazard is Hazard.DANGEROUS and not allow_dangerous:
        raise DangerousCommandError(
            f"{code} is untraced/unverified (control-band, calibration, or "
            "unknown opcode); pass allow_dangerous=True to override"
        )
    return hazard
