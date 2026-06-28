"""Exception hierarchy for whiskerless."""

from __future__ import annotations


class WhiskerlessError(Exception):
    """Base class for every error raised by this library."""


class SafetyError(WhiskerlessError):
    """A command was refused by the safety guard."""


class NeverSendError(SafetyError):
    """An always-forbidden brick/reset-class command was refused.

    This is unconditional — there is no flag that lets it through. The opcodes
    in :data:`whiskerless.safety.NEVER_SEND_OPCODES` can corrupt the main-board
    flash or the globe-motor controller, so the library refuses to put them on
    the wire at all.
    """


class MotorCommandError(SafetyError):
    """A motor command (clean cycle) was refused without explicit opt-in."""


class DangerousCommandError(SafetyError):
    """An untraced / control-band / calibration write was refused.

    These registers are unverified or contradicted by the reverse-engineering
    and can corrupt persisted scale/ToF calibration or trip an unknown action.
    Pass ``allow_dangerous=True`` only if you know exactly what you are doing.
    """


class WhiskerlessConnectionError(WhiskerlessError):
    """Could not connect to (or lost the connection to) the robot's broker."""


class WhiskerlessAuthError(WhiskerlessError):
    """The broker rejected the supplied MQTT credentials."""


class ProtocolError(WhiskerlessError):
    """A malformed or unparseable wire payload."""


class ProvisioningError(WhiskerlessError):
    """A BLE re-provisioning step failed."""
