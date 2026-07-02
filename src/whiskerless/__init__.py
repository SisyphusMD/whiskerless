"""whiskerless — un-cloud your Whisker devices.

A small, typed library for fully-local MQTT control + telemetry of Whisker
robots (Litter-Robot 4 today). The codec and command catalog are device-specific
under :mod:`whiskerless.devices`; :mod:`whiskerless.safety` is the guard that
keeps brick/reset-class commands off the wire no matter who calls.
"""

from __future__ import annotations

from .exceptions import (
    DangerousCommandError,
    MotorCommandError,
    NeverSendError,
    ProtocolError,
    ProvisioningError,
    SafetyError,
    WhiskerlessAuthError,
    WhiskerlessConnectionError,
    WhiskerlessError,
)
from .mqtt import MqttSettings
from .safety import Hazard, assert_sendable, classify_code

__version__ = "0.1.3"

__all__ = [
    "DangerousCommandError",
    "Hazard",
    "MotorCommandError",
    "MqttSettings",
    "NeverSendError",
    "ProtocolError",
    "ProvisioningError",
    "SafetyError",
    "WhiskerlessAuthError",
    "WhiskerlessConnectionError",
    "WhiskerlessError",
    "__version__",
    "assert_sendable",
    "classify_code",
]
