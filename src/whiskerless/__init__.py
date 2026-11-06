"""whiskerless — un-cloud your Whisker devices.

A small, typed library for fully-local MQTT control + telemetry of Whisker
robots (Litter-Robot 4 today), plus a cloud bridge
(:mod:`whiskerless.bridge`) that keeps Whisker's cloud working for a robot on a
local broker. The codec and command catalog are device-specific
under :mod:`whiskerless.devices`; :mod:`whiskerless.safety` is the guard that
keeps brick/reset-class commands off the wire no matter who calls.
"""

from __future__ import annotations

from .bridge import (
    BridgeDirection,
    BridgeTraffic,
    CloudBridge,
    CloudIdentity,
    TopicMap,
    check_injected_command,
    cloud_settings,
)
from .exceptions import (
    DangerousCommandError,
    NeverSendError,
    ProtocolError,
    ProvisioningError,
    SafetyError,
    WhiskerlessConnectionError,
    WhiskerlessError,
)
from .mqtt import MqttSettings
from .safety import Hazard, assert_sendable, classify_code

__version__ = "0.1.3"

__all__ = [
    "BridgeDirection",
    "BridgeTraffic",
    "CloudBridge",
    "CloudIdentity",
    "DangerousCommandError",
    "Hazard",
    "MqttSettings",
    "NeverSendError",
    "ProtocolError",
    "ProvisioningError",
    "SafetyError",
    "TopicMap",
    "WhiskerlessConnectionError",
    "WhiskerlessError",
    "__version__",
    "assert_sendable",
    "check_injected_command",
    "classify_code",
    "cloud_settings",
]
