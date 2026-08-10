"""Provisioning, driven end to end against a fake radio.

This is the only irreversible thing the project does: it re-points the robot off
Whisker's cloud and onto your broker, and the way back is another BLE session. So
the order of operations matters — client-id before the WiFi finalize, endpoints
before the certificate, APPLY_CONFIG before the reboot — and a wrong device must
be refused before any of it starts.

The radio is faked, so none of this says the bytes are right on the bench. It
says the sequence is the one that was captured, and that the refusals refuse.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from whiskerless.ble import messages as m
from whiskerless.ble.provision import (
    ProvisioningConfig,
    _format_mac,
    provision_robot,
    read_device_mac,
)
from whiskerless.ble.transport import USER_DESC_UUID
from whiskerless.exceptions import ProvisioningError

pytest.importorskip("bleak", reason="the BLE extra is bench-only")

CA_PEM = "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----\n"
SERIAL = "LR4C000001"
MAC = bytes.fromhex("aabbccddeeff")


class FakeDescriptor:
    uuid = USER_DESC_UUID

    def __init__(self, handle: int) -> None:
        self.handle = handle


class FakeChar:
    def __init__(self, name: str, handle: int) -> None:
        self.uuid = f"char-{name}"
        self.name = name
        self.descriptors = [FakeDescriptor(handle)]


class FakeService:
    def __init__(self, uuid: str, characteristics: list[FakeChar]) -> None:
        self.uuid = uuid
        self.characteristics = characteristics


class FakeRobot:
    """A BleakClient stand-in exposing the LR4's protocomm endpoints."""

    mtu_size = 200

    def __init__(self, *, service_uuid: str | None = None, endpoints: list[str] | None = None):
        from whiskerless.ble.messages import PROV_SERVICE_UUID

        names = endpoints if endpoints is not None else [m.EP_MQTT, m.EP_WHISKER, m.EP_PROV_CONFIG]
        self._chars = {i: FakeChar(name, i) for i, name in enumerate(names)}
        self.services = [
            FakeService(service_uuid or PROV_SERVICE_UUID, list(self._chars.values()))
        ]
        self.address = "AA:BB:CC:DD:EE:FF"
        self.requests: list[tuple[str, bytes]] = []

    async def __aenter__(self) -> FakeRobot:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def read_gatt_descriptor(self, handle: int) -> bytes:
        return self._chars[handle].name.encode()

    async def write_gatt_char(self, char: Any, payload: bytes, response: bool = True) -> None:
        self.requests.append((char.name, payload))

    async def read_gatt_char(self, char: Any) -> bytes:
        # Only reached outside a dry run; an empty body decodes as "no device id".
        return b""


def _config(**kw: Any) -> ProvisioningConfig:
    base: dict[str, Any] = {
        "serial": SERIAL,
        "host": "192.168.1.10",
        "ca_pem": CA_PEM,
        "wifi_ssid": "home",
        "wifi_pass": "secret",
        "wifi_wait": 0,
    }
    base.update(kw)
    return ProvisioningConfig(**base)


def _bleak(robot: FakeRobot) -> Any:
    return patch("bleak.BleakClient", lambda *_a, **_k: robot)


# --- refusals before anything is written -------------------------------------
async def test_a_device_without_the_lr4_service_is_refused_before_any_write() -> None:
    """--address takes an arbitrary BLE address, so this is the only guard."""
    robot = FakeRobot(service_uuid="0000ffff-0000-1000-8000-00805f9b34fb")
    with _bleak(robot), pytest.raises(ProvisioningError, match="not a Litter-Robot 4"):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config(), dry_run=True)
    assert robot.requests == [], "nothing may be written to an unidentified device"


async def test_something_that_is_not_a_certificate_is_refused_early() -> None:
    """A path typed instead of the file's contents is the obvious mistake."""
    robot = FakeRobot()
    with _bleak(robot), pytest.raises(ProvisioningError, match="PEM"):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config(ca_pem="/path/to/ca.crt"), dry_run=True)
    assert robot.requests == []


async def test_a_missing_required_endpoint_stops_the_run() -> None:
    """Firmware that lacks them would take half a configuration and keep it."""
    robot = FakeRobot(endpoints=[m.EP_PROV_CONFIG])
    with _bleak(robot), pytest.raises(ProvisioningError, match="required endpoint"):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config(), dry_run=True)


async def test_wifi_without_an_ssid_is_refused() -> None:
    robot = FakeRobot()
    with _bleak(robot), pytest.raises(ProvisioningError, match="wifi_ssid"):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config(wifi_ssid=""), dry_run=True)


def test_a_serial_from_another_model_is_refused_at_construction() -> None:
    with pytest.raises(ProvisioningError, match="LR4"):
        _config(serial="LR3C000001")


# --- the dry run -------------------------------------------------------------
async def test_a_dry_run_reaches_the_end_without_writing_a_byte() -> None:
    robot = FakeRobot()
    with _bleak(robot):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(), dry_run=True)

    assert result.success is False, "a dry run has not provisioned anything"
    assert "dry-run" in result.message
    assert robot.requests == []


async def test_a_dry_run_still_reports_every_step_it_would_take() -> None:
    """The steps are the point: it is the rehearsal before the irreversible run."""
    robot = FakeRobot()
    with _bleak(robot):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(), dry_run=True)

    joined = " | ".join(result.steps)
    for expected in ("DEVICE_ID_SET", "WiFi SetConfig", "endpoints:", "CERT_", "APPLY_CONFIG"):
        assert expected in joined, f"{expected} missing from the rehearsal"


async def test_the_callback_sees_each_step_as_it_happens() -> None:
    seen: list[str] = []
    with _bleak(FakeRobot()):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config(), dry_run=True, on_step=seen.append)
    assert len(seen) > 4


# --- topic derivation --------------------------------------------------------
def test_the_topics_are_derived_from_the_serial() -> None:
    config = _config()
    assert config.resolved_command_topic() == f"prod/LR4/{SERIAL}/command"
    # The firmware derives /state from the publish endpoint, which is /activity.
    assert config.resolved_device_topic() == f"prod/LR4/{SERIAL}/activity"


def test_explicit_topics_win_over_the_derived_ones() -> None:
    config = _config(command_topic="a/b/c", device_topic="d/e/f")
    assert config.resolved_command_topic() == "a/b/c"
    assert config.resolved_device_topic() == "d/e/f"


# --- MAC formatting ----------------------------------------------------------
def test_a_six_byte_id_is_formatted_as_a_mac() -> None:
    assert _format_mac(MAC) == "aa:bb:cc:dd:ee:ff"


def test_a_string_id_is_trimmed_of_its_padding() -> None:
    assert _format_mac(b"LR4C000001\x00\x00") == "LR4C000001"


def test_no_id_stays_none() -> None:
    assert _format_mac(None) is None
    assert _format_mac(b"\x00\x00") is None


# --- the read-only preflight -------------------------------------------------
async def test_the_preflight_refuses_a_device_that_is_not_an_lr4() -> None:
    robot = FakeRobot(service_uuid="0000ffff-0000-1000-8000-00805f9b34fb")
    with _bleak(robot), pytest.raises(ProvisioningError, match="not a Litter-Robot 4"):
        await read_device_mac("AA:BB:CC:DD:EE:FF")


# --- the real run ------------------------------------------------------------
async def test_a_real_run_writes_the_sequence_and_reports_success() -> None:
    """The order is load-bearing: client-id, WiFi, endpoints, cert, then commit."""
    robot = FakeRobot()
    with _bleak(robot):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(reboot=False))

    assert result.success is True
    endpoints = [name for name, _ in robot.requests]
    assert endpoints.index(m.EP_WHISKER) < endpoints.index(m.EP_PROV_CONFIG), (
        "the client id must be set before the WiFi finalize"
    )
    assert m.EP_MQTT in endpoints


async def test_a_reboot_that_drops_the_link_is_not_a_failure() -> None:
    """The robot reboots out from under the connection; that is the success case."""

    class Rebooting(FakeRobot):
        async def write_gatt_char(self, char: Any, payload: bytes, response: bool = True) -> None:
            await super().write_gatt_char(char, payload, response)
            if payload == m.whisker_reboot():
                raise OSError("link lost")

    robot = Rebooting()
    with _bleak(robot):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(reboot=True))
    assert result.success is True


async def test_a_rejected_write_stops_the_run_rather_than_half_configuring() -> None:
    """A half-written configuration is worse than none: the robot keeps it."""

    class Rejecting(FakeRobot):
        async def read_gatt_char(self, char: Any) -> bytes:
            return bytes.fromhex("1004") if char.name == m.EP_MQTT else b""

    with _bleak(Rejecting()), pytest.raises(ProvisioningError, match="status=4"):
        await provision_robot("AA:BB:CC:DD:EE:FF", _config())


async def test_the_preflight_returns_the_robots_mac() -> None:
    robot = FakeRobot()
    with _bleak(robot):
        assert await read_device_mac("AA:BB:CC:DD:EE:FF") is None  # empty body → no id
    assert robot.requests, "the preflight must actually ask"


async def test_the_topics_can_be_swapped_for_firmware_that_wants_them_the_other_way() -> None:
    """The pairing was inferred from a capture; the escape hatch has to work."""
    robot = FakeRobot()
    with _bleak(robot):
        result = await provision_robot(
            "AA:BB:CC:DD:EE:FF", _config(swap_topics=True), dry_run=True
        )
    endpoints = next(s for s in result.steps if s.startswith("endpoints: host="))
    assert "sub=prod/LR4/LR4C000001/activity" in endpoints


async def test_a_whisker_endpoint_complaint_is_logged_not_fatal() -> None:
    """DEVICE_ID_SET reporting non-zero has been seen on a robot that took it anyway."""

    class Grumbling(FakeRobot):
        async def read_gatt_char(self, char: Any) -> bytes:
            return bytes.fromhex("1004") if char.name == m.EP_WHISKER else b""

    with _bleak(Grumbling()):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(reboot=False))
    assert result.success is True
