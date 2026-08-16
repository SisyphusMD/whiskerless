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

import asyncio
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


async def test_a_dry_run_marks_every_line_a_human_reads() -> None:
    """Otherwise "CERT_AWS_ROOT_CERT written" describes a robot nothing touched."""
    shown: list[str] = []
    with _bleak(FakeRobot()):
        await provision_robot(
            "AA:BB:CC:DD:EE:FF", _config(), dry_run=True, on_step=shown.append
        )
    assert shown, "the run must report something"
    assert all(line.startswith("[dry-run] ") for line in shown)
    assert any("not read (dry-run)" in line for line in shown)


async def test_a_real_run_marks_nothing() -> None:
    shown: list[str] = []
    with _bleak(FakeRobot()):
        await provision_robot(
            "AA:BB:CC:DD:EE:FF", _config(reboot=False), on_step=shown.append
        )
    assert shown and not any("dry-run" in line for line in shown)


async def test_a_whisker_endpoint_complaint_is_logged_not_fatal() -> None:
    """DEVICE_ID_SET reporting non-zero has been seen on a robot that took it anyway."""

    class Grumbling(FakeRobot):
        async def read_gatt_char(self, char: Any) -> bytes:
            return bytes.fromhex("1004") if char.name == m.EP_WHISKER else b""

    with _bleak(Grumbling()):
        result = await provision_robot("AA:BB:CC:DD:EE:FF", _config(reboot=False))
    assert result.success is True


# --- prov-scan: asking the robot what it can see ------------------------------
def test_scan_results_fold_a_sign_extended_rssi() -> None:
    """RSSI is an int32 sign-extended into a varint, so -51 arrives as 2**64-51.
    Reported raw it is a signal strength of eighteen quintillion dBm."""
    from whiskerless.ble import messages as m
    from whiskerless.ble.protobuf import field_message, field_string, field_varint

    entry = field_string(1, "MyIoT") + field_varint(2, 6) + field_varint(3, (1 << 64) - 51)
    payload = field_message(15, field_message(1, entry))
    (network,) = m.parse_scan_results(payload)
    assert (network.ssid, network.channel, network.rssi) == ("MyIoT", 6, -51)


def test_scan_results_drop_entries_with_no_usable_name() -> None:
    """A hidden network cannot be picked from a list by name, and the SSID field
    is raw bytes that need not be valid UTF-8."""
    from whiskerless.ble import messages as m
    from whiskerless.ble.protobuf import field_message, field_string, field_varint

    good = field_string(1, "MyIoT") + field_varint(3, (1 << 64) - 40)
    hidden = field_string(1, "") + field_varint(3, (1 << 64) - 50)
    payload = field_message(15, field_message(1, good) + field_message(1, hidden))
    assert [n.ssid for n in m.parse_scan_results(payload)] == ["MyIoT"]


class _ScanTransport:
    """Answers the prov-scan conversation: start, status, then paged results."""

    def __init__(self, networks: list[tuple[str, int]], *, finish_after: int = 1) -> None:
        self.networks = networks
        self.finish_after = finish_after
        self.polls = 0
        self.pages: list[tuple[int, int]] = []

    async def request(self, endpoint: str, payload: bytes) -> bytes:
        from whiskerless.ble.protobuf import field_message, field_string, field_varint, read_fields

        fields = read_fields(payload)
        if 12 in fields:                                   # CmdScanStatus
            self.polls += 1
            done = self.polls >= self.finish_after
            inner = field_varint(1, int(done)) + field_varint(2, len(self.networks))
            return field_message(13, inner)
        if 14 in fields:                                   # CmdScanResult
            arm = read_fields(fields[14][0])
            # proto3 implicit presence: a zero start_index is omitted on the
            # wire, and protobuf-c reads the missing field back as 0 — so the
            # double has to default the same way the firmware does.
            start = int(arm[1][0]) if 1 in arm else 0
            count = int(arm[2][0]) if 2 in arm else 0
            self.pages.append((start, count))
            body = b""
            for ssid, rssi in self.networks[start:start + count]:
                body += field_message(
                    1, field_string(1, ssid) + field_varint(2, 6)
                    + field_varint(3, (1 << 64) + rssi)
                )
            return field_message(15, body)
        return b""                                          # CmdScanStart


async def test_the_scan_is_paged_and_sorted_strongest_first() -> None:
    from whiskerless.ble.provision import SCAN_PAGE, scan_networks

    transport = _ScanTransport([("far", -80), ("near", -35), ("mid", -60), ("x", -70), ("y", -75)])
    found = await scan_networks(transport)  # type: ignore[arg-type]
    assert [n.ssid for n in found] == ["near", "mid", "x", "y", "far"]
    assert transport.pages == [(0, SCAN_PAGE), (4, SCAN_PAGE)], "results are fetched in pages"


async def test_a_mesh_network_appears_once_at_its_strongest() -> None:
    """One SSID per access point would list the same name six times, which is not
    a choice anyone can make."""
    from whiskerless.ble.provision import scan_networks

    transport = _ScanTransport([("Mesh", -70), ("Mesh", -41), ("Other", -60), ("Mesh", -85)])
    found = await scan_networks(transport)  # type: ignore[arg-type]
    assert [(n.ssid, n.rssi) for n in found] == [("Mesh", -41), ("Other", -60)]


async def test_a_scan_that_never_finishes_gives_up() -> None:
    from whiskerless.ble import provision as prov
    from whiskerless.exceptions import ProvisioningError

    transport = _ScanTransport([("MyIoT", -40)], finish_after=10_000)
    with patch.object(prov, "SCAN_TIMEOUT", 0.0), pytest.raises(ProvisioningError, match="did not finish"):
        await prov.scan_networks(transport)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("rssi", "bars"), [(-40, 4), (-60, 4), (-65, 3), (-75, 2), (-95, 1)]
)
def test_signal_becomes_bars_a_person_can_read(rssi: int, bars: int) -> None:
    assert m.WifiNetwork(ssid="x", channel=1, rssi=rssi, secured=True).bars == bars


@pytest.mark.parametrize("payload", [b"", b"\x08\x01", m.wifi_scan_status()])
def test_a_reply_that_is_not_a_scan_status_reads_as_none(payload: bytes) -> None:
    """Anything but the RespScanStatus arm means "no verdict", never a fake one."""
    assert m.parse_scan_status(payload) is None


@pytest.mark.parametrize("payload", [b"", b"\x08\x01"])
def test_a_reply_that_is_not_a_scan_result_reads_as_empty(payload: bytes) -> None:
    assert m.parse_scan_results(payload) == []


def test_scan_results_skip_an_ssid_that_is_not_utf8() -> None:
    from whiskerless.ble.protobuf import WIRE_LEN, _tag, encode_varint, field_message

    bad = _tag(1, WIRE_LEN) + encode_varint(2) + b"\xff\xfe"
    assert m.parse_scan_results(field_message(15, field_message(1, bad))) == []


def test_scan_status_without_a_count_still_reads() -> None:
    """proto3 omits a zero result_count, and a finished-but-empty scan is real."""
    from whiskerless.ble.protobuf import field_message, field_varint

    payload = field_message(13, field_varint(1, 1))
    assert m.parse_scan_status(payload) == (True, 0)


async def test_the_scan_is_polled_until_the_robot_says_it_finished() -> None:
    """The first status almost always says "still scanning" — the poll loop is
    the normal path, not an edge case."""
    from whiskerless.ble.provision import scan_networks

    transport = _ScanTransport([("MyIoT", -42)], finish_after=3)
    found = await scan_networks(transport)  # type: ignore[arg-type]
    assert [n.ssid for n in found] == ["MyIoT"]
    assert transport.polls == 3


def test_an_unknown_failure_reason_is_reported_without_a_name() -> None:
    """The enum has two members; firmware is free to invent a third, and an
    unrecognised number must not take the whole status decode down."""
    from whiskerless.ble.protobuf import field_message, field_varint

    payload = field_message(11, field_message(11, b"") if False else field_varint(10, 99))
    status = m.parse_wifi_status(payload)
    assert status is not None
    assert status.state is m.WifiStationState.CONNECTION_FAILED
    assert status.fail_reason is None


def test_scan_results_skip_an_entry_that_is_not_a_message() -> None:
    """A varint where a sub-message belongs is malformed, not fatal."""
    from whiskerless.ble.protobuf import field_message, field_varint

    assert m.parse_scan_results(field_message(15, field_varint(1, 7))) == []


def test_scan_results_skip_an_explicitly_empty_ssid() -> None:
    """proto3 omits an empty string, but a peer may still send the field with a
    zero length — a network with no name cannot be offered in a list."""
    from whiskerless.ble.protobuf import WIRE_LEN, _tag, encode_varint, field_message

    empty = _tag(1, WIRE_LEN) + encode_varint(0)
    assert m.parse_scan_results(field_message(15, field_message(1, empty))) == []


async def test_provisioning_asks_the_robot_for_networks_when_no_ssid_was_given() -> None:
    """The chooser runs on the open BLE link, between the device-id read and the
    first write, so a robot whose owner backs out is still untouched."""
    robot = FakeRobot()
    offered: list[list[m.WifiNetwork]] = []

    async def chooser(networks: list[m.WifiNetwork]) -> tuple[str, str]:
        offered.append(networks)
        return "PickedFromList", "pw"

    async def fake_scan(_transport: Any) -> list[m.WifiNetwork]:
        return [m.WifiNetwork(ssid="Seen", channel=1, rssi=-40, secured=True)]

    with _bleak(robot), patch("whiskerless.ble.provision.scan_networks", fake_scan):
        result = await provision_robot(
            "AA:BB", _config(wifi_ssid="", wifi_pass=""), choose_network=chooser
        )
    assert result.success
    assert offered, "the robot was asked what it can see"
    assert any(b"PickedFromList" in payload for _ep, payload in robot.requests)


async def test_provisioning_stops_when_no_network_is_chosen() -> None:
    """Backing out of the list must not fall through to provisioning a blank SSID."""
    robot = FakeRobot()

    async def chooser(_networks: list[m.WifiNetwork]) -> tuple[str, str]:
        return "", ""

    async def fake_scan(_transport: Any) -> list[m.WifiNetwork]:
        return []

    with (
        _bleak(robot),
        patch("whiskerless.ble.provision.scan_networks", fake_scan),
        pytest.raises(ProvisioningError, match="no WiFi network chosen"),
    ):
        await provision_robot(
            "AA:BB", _config(wifi_ssid="", wifi_pass=""), choose_network=chooser
        )


async def test_a_supplied_ssid_skips_the_network_list_entirely() -> None:
    """A scripted run named its network; asking the robot would be a round trip
    nobody needs and a prompt nobody can answer."""
    robot = FakeRobot()
    called = False

    async def chooser(_networks: list[m.WifiNetwork]) -> tuple[str, str]:
        nonlocal called
        called = True
        return "x", "y"

    with _bleak(robot):
        assert (await provision_robot("AA:BB", _config(), choose_network=chooser)).success
    assert not called


async def test_a_dry_run_does_not_drive_the_network_scan() -> None:
    """A dry run answers every request with b"", so scanning through it would poll
    until the timeout and fail the rehearsal it is supposed to be."""
    robot = FakeRobot()
    asked: list[list[m.WifiNetwork]] = []

    async def chooser(networks: list[m.WifiNetwork]) -> tuple[str, str]:
        asked.append(networks)
        return "Typed", "pw"

    with _bleak(robot):
        result = await provision_robot(
            "AA:BB", _config(wifi_ssid="", wifi_pass=""), dry_run=True, choose_network=chooser
        )
    assert result.message == "dry-run: no bytes written"
    assert asked == [[]], "the chooser is offered nothing and falls back to typing"


def test_an_open_network_is_not_shown_with_a_lock() -> None:
    """Auth mode 0 IS open, and proto3 omits a zero default — so an absent auth
    field means an open network, not an unknown one."""
    from whiskerless.ble.protobuf import field_message, field_string, field_varint

    open_ap = field_string(1, "Cafe") + field_varint(3, (1 << 64) - 55)
    wpa = field_string(1, "Home") + field_varint(3, (1 << 64) - 45) + field_varint(5, 3)
    found = m.parse_scan_results(
        field_message(15, field_message(1, open_ap) + field_message(1, wpa))
    )
    assert {n.ssid: n.secured for n in found} == {"Cafe": False, "Home": True}


def test_an_ssid_with_terminal_escapes_is_escaped_for_display() -> None:
    """An SSID is bytes chosen by whoever runs the AP; valid UTF-8 still carries
    newlines and ANSI escapes, and the chooser prints these into a terminal."""
    hostile = m.WifiNetwork(ssid="Guest\x1b[31m\nEvil", channel=1, rssi=-40, secured=True)
    assert hostile.display == "Guest\\x1bs[31m\\x0aEvil".replace("s[", "[")
    assert hostile.ssid == "Guest\x1b[31m\nEvil", "the real SSID is what gets provisioned"


async def test_a_scan_that_stalls_on_the_blocking_start_is_bounded() -> None:
    """wifi_scan_start blocks until the sweep finishes, so the timeout has to
    cover it — deadlining only the poll loop leaves a stalled read unbounded."""
    from whiskerless.ble import provision as prov

    class _Stalls:
        async def request(self, endpoint: str, payload: bytes) -> bytes:
            await asyncio.sleep(3600)
            return b""

    with patch.object(prov, "SCAN_TIMEOUT", 0.05), pytest.raises(ProvisioningError, match="did not finish"):
        await prov.scan_networks(_Stalls())  # type: ignore[arg-type]
