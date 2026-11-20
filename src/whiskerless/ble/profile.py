"""What a robot model supplies to the shared BLE provisioning sequence.

The sequence itself (WiFi, broker endpoints, certificates, apply, reboot) is the
same protocomm exchange on every model that speaks it. What differs per model is
how to recognise the robot and what its identity and default topics look like, so
that lives with the model under ``devices/`` and reaches ``ble`` as one of these.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProvisioningProfile:
    """One robot model's discovery, identity and topic rules."""

    #: Human name used in messages, e.g. ``"Litter-Robot 4"``.
    model: str
    #: The protocomm GATT service UUID. Scanning matches on it, and the connection
    #: must expose it before anything is written.
    service_uuid: str
    #: The advertised name, a weaker fallback match for scans that miss the UUID.
    advertiser_name: str
    #: Normalize a typed serial, or raise ``ProvisioningError`` explaining why it
    #: cannot be one. The serial becomes the robot's MQTT client-id.
    check_serial: Callable[[str], str]
    #: Default topic the robot subscribes to for commands, given its serial.
    command_topic: Callable[[str], str]
    #: Default topic the robot publishes on, given its serial.
    device_topic: Callable[[str], str]
