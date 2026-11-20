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
because the mechanism is known. The same holds for a type byte other than
``01`` or ``02``. It was assumed to be ignored, but never tried, and the one
unknown field that was tried points the other way: an unknown panel press type
is normalised to a short press and performed. So it needs ``allow_dangerous``,
and never-send targets stay refused. A setting value outside the range verified
for its register is handled the same way: writes inside the range were read back,
and what the firmware does with one past it has not been seen.

The command grammar guarded here is the LR4 ESP wire format: a 10-character
string ``0xTTRRVVVV`` where ``TT`` is the type (``01``=read, ``02``=write/macro),
``RR`` the register/opcode, and ``VVVV`` the 16-bit value.
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

#: Plain registers refused at any value. `0x2D` is the PIC factory reset according
#: to a reference written by sniffing the ESP-PIC UART directly (the
#: esphome-litter-robot project), never tried here. A reset wipes every setting on
#: the robot and gains nothing, so the claim alone is enough to refuse it.
NEVER_SEND_REGISTERS: frozenset[int] = frozenset({0x2D})

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
#: Every other button value stays DANGEROUS. Two are deliberately left out even
#: though both are known-good writes: Power (0x0101) and Connect (0x1001). Both
#: toggle, and both can end with the robot off the network — powered down, or
#: with its WiFi switched off — where nothing over MQTT reaches it and only
#: someone at the machine can undo it. Those are the two panel buttons whose cost
#: is losing control of the device rather than moving litter around.
#:
#: Long presses cannot be synthesised at all — the firmware performs press type
#: 01 and silently declines 02 — so the hold-only chords never reach here.

#: Report macros that are safe to send with a zero value (PROVEN live). A
#: non-zero value on these indexes a firmware jump table, so it is treated as
#: dangerous instead.
SAFE_REPORT_MACROS: frozenset[int] = frozenset({0xA0, 0xA1, 0xA7, 0xA9, 0xAE})

_MINUTES_OF_DAY = range(1440)

#: Settings registers and the values verified for each: the setting's own domain
#: (an enum, a percentage, minutes since midnight, the seven-day mask, the span
#: the app offers), inside which live writes were read back. A value outside its
#: range is a write nobody has seen land, so it is DANGEROUS, not SAFE. 0x1A-0x1C
#: are read-only views whose refused writes are acknowledged and discarded; they
#: are bounded the same way because the discard was only seen inside the domain.
#: 0x05 (debug mode) is absent: no write to it has ever been recorded.
SAFE_SETTING_VALUES: dict[int, range] = {
    0x16: range(3, 31),       # clean-cycle wait, minutes; written at 3, 7 and 20
    0x17: range(2),           # keypad lockout
    0x18: range(3),           # night light off / on / auto
    0x19: range(101),         # night-light brightness, %
    0x1A: range(2),
    0x1B: _MINUTES_OF_DAY,
    0x1C: _MINUTES_OF_DAY,
    0x1D: range(0x80),        # bit i arms weekday i, Sunday-first
    **dict.fromkeys(range(0x1E, 0x2C), _MINUTES_OF_DAY),
}

#: Panel brightness packs two levels into one value, hi byte for a bright room
#: and lo byte for a dark one, so the range applies to each byte. A range on the
#: packed value would pass 0x00FF.
PANEL_BRIGHTNESS_REGISTER: int = 0x0E
PANEL_BRIGHTNESS_LEVELS: range = range(101)


class Hazard(Enum):
    """How dangerous a parsed command is."""

    SAFE = "safe"            # read, report macro (value 0), or verified settings write
    DANGEROUS = "dangerous"  # untraced, unverified value, or unknown type
    NEVER = "never"          # brick / reset-class — unconditionally refused


class CommandType(Enum):
    """The wire ``TT`` type byte."""

    READ = 1
    WRITE = 2
    UNKNOWN = 0  # any other byte; reportedly ignored by the firmware, never tested


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
        type_byte = int(raw[2:4], 16)
        register = int(raw[4:6], 16)
        value = int(raw[6:10], 16)
    except ValueError as exc:
        raise ProtocolError(f"non-hex digits in command {code!r}") from exc

    try:
        ctype = CommandType(type_byte)
    except ValueError:
        ctype = CommandType.UNKNOWN
    return ctype, register, value


def classify(ctype: CommandType, register: int, value: int) -> Hazard:
    """Classify a parsed command into a :class:`Hazard`."""
    if ctype is CommandType.READ:
        return Hazard.SAFE  # type-1 read builds a GET frame — structurally read-only

    # An unknown type is checked against the never-send set as though it were a
    # write: if the firmware does not ignore it, the opt-in must not unlock a reset.
    if register in NEVER_SEND_OPCODES or register in NEVER_SEND_REGISTERS:
        return Hazard.NEVER
    if register == PANEL_BUTTON_REGISTER and value in PANEL_BUTTON_NEVER:
        return Hazard.NEVER
    if ctype is CommandType.UNKNOWN:
        return Hazard.DANGEROUS

    # type-2: macro dispatch or generic register write.
    if register == PANEL_BUTTON_REGISTER:
        # By value: the same register runs the globe, acknowledges an alarm, or
        # factory-resets the robot depending only on which bits are set.
        if value in PANEL_BUTTON_SAFE:
            return Hazard.SAFE
        return Hazard.DANGEROUS
    if register in SAFE_REPORT_MACROS:
        return Hazard.SAFE if value == 0 else Hazard.DANGEROUS
    if register == PANEL_BRIGHTNESS_REGISTER:
        high, low = value >> 8, value & 0xFF
        if high in PANEL_BRIGHTNESS_LEVELS and low in PANEL_BRIGHTNESS_LEVELS:
            return Hazard.SAFE
        return Hazard.DANGEROUS
    if register in SAFE_SETTING_VALUES:
        return Hazard.SAFE if value in SAFE_SETTING_VALUES[register] else Hazard.DANGEROUS
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
            f"{code} is untraced/unverified (unknown opcode, unknown command "
            "type, or a setting value outside its verified range); pass "
            "allow_dangerous=True to override"
        )
    return hazard
