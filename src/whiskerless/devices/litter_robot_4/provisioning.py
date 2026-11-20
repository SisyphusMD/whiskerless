"""Litter-Robot 4 discovery, identity and default topics for BLE provisioning."""

from __future__ import annotations

from ...ble.profile import ProvisioningProfile
from ...exceptions import ProvisioningError

# Intrinsic to every LR4's protocomm GATT service, unlike the advertised name,
# which the robot broadcasts weakly and intermittently.
SERVICE_UUID = "b7ee1c20-dcfd-4208-8813-14845cac5212"
ADVERTISER_NAME = "LitterRobot4"


def check_serial(value: str) -> str:
    """Normalize a typed serial, or explain why it cannot be one.

    The serial becomes the MQTT client-id and both topic segments, so a wrong
    value provisions cleanly and then never appears on the broker — there is
    no error to see. It is worth rejecting early.

    The shape rule is deliberately loose: only two units have ever been seen
    here, both ``LR4C`` + six digits, which is far too small a sample to
    insist on. Requiring some length and some digits is enough to reject the
    model designator printed beside the serial on the same label, which is
    the mistake this actually catches.
    """
    serial = value.strip().upper()
    if not serial.startswith("LR4"):
        raise ProvisioningError(
            f"serial {serial!r} is not a Litter-Robot 4 serial "
            "(expected LR4…, e.g. LR4C123456) — this provisioner only supports the LR4"
        )
    # The hyphen test is what actually catches the label's other line: the
    # designator (LR4-0301-00-US) is long enough and carries enough digits
    # to pass the shape checks below.
    if "-" in serial or len(serial) < 8 or sum(character.isdigit() for character in serial) < 4:
        raise ProvisioningError(
            f"serial {serial!r} looks like the model number, not the serial — the serial is "
            "the longer line, LR4 followed by a letter and six digits (e.g. LR4C123456)"
        )
    return serial


def command_topic(serial: str) -> str:
    return f"prod/LR4/{serial}/command"


def device_topic(serial: str) -> str:
    # The app points the device (publish) endpoint at /activity; the firmware
    # derives the /state sub-topic from it.
    return f"prod/LR4/{serial}/activity"


PROFILE = ProvisioningProfile(
    model="Litter-Robot 4",
    service_uuid=SERVICE_UUID,
    advertiser_name=ADVERTISER_NAME,
    check_serial=check_serial,
    command_topic=command_topic,
    device_topic=device_topic,
)
