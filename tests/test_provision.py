"""Provisioning guards — LR4-only serial validation, the GATT model check, and
the WiFi join verify (a mistyped password must fail loud, not silently)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from whiskerless.ble import provision as provision_module
from whiskerless.ble.messages import (
    EP_PROV_CONFIG,
    PROV_SERVICE_UUID,
    WifiConnectFailedReason,
    WifiStationState,
    parse_wifi_status,
    wifi_get_status,
)
from whiskerless.ble.protobuf import field_message, field_string, field_varint
from whiskerless.ble.provision import ProvisioningConfig, _assert_lr4, _verify_wifi
from whiskerless.exceptions import ProvisioningError

CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _config(serial: str) -> ProvisioningConfig:
    return ProvisioningConfig(serial=serial, host="192.168.1.10", ca_pem=CA_PEM)


def test_serial_lr4_accepted() -> None:
    assert _config("LR4C123456").serial == "LR4C123456"


def test_serial_normalized_upper_and_stripped() -> None:
    assert _config("  lr4c123456 ").serial == "LR4C123456"


@pytest.mark.parametrize("serial", ["", "LR3C123456", "FR1A000001", "123456", "WR4C123456"])
def test_serial_non_lr4_refused(serial: str) -> None:
    with pytest.raises(ProvisioningError, match="not a Litter-Robot 4 serial"):
        _config(serial)


@dataclass
class _FakeService:
    uuid: str


@dataclass
class _FakeClient:
    address: str
    services: list[_FakeService]


def test_assert_lr4_passes_on_provisioning_service() -> None:
    client = _FakeClient("AA:BB:CC:DD:EE:FF", [_FakeService(PROV_SERVICE_UUID.upper())])
    _assert_lr4(client)  # type: ignore[arg-type]


def test_assert_lr4_refuses_other_devices() -> None:
    client = _FakeClient("AA:BB:CC:DD:EE:FF", [_FakeService("0000180a-0000-1000-8000-00805f9b34fb")])
    with pytest.raises(ProvisioningError, match="not a Litter-Robot 4"):
        _assert_lr4(client)  # type: ignore[arg-type]


# --- WiFi join verification ---------------------------------------------------
# RespGetStatus wire fixtures, built exactly as protobuf-c emits them.


def _resp_get_status(inner: bytes) -> bytes:
    # WiFiConfigPayload: msg=1 (TypeRespGetStatus) + oneof arm 11 = RespGetStatus.
    return field_varint(1, 1) + field_message(11, inner)


CONNECTED = _resp_get_status(
    # sta_state=0 (Connected) is a proto3 default and stays off the wire; the
    # WifiConnectedState arm (field 11: ip4_addr + channel) carries the verdict.
    field_message(11, field_string(1, "192.168.2.41") + field_varint(5, 6))
)
# fail_reason AuthError is enum value 0, but oneof presence is explicit, so
# protobuf-c emits the field anyway: tag 10<<3|0 = 0x50, value 0x00.
AUTH_ERROR = _resp_get_status(field_varint(2, 3) + b"\x50\x00")
NETWORK_NOT_FOUND = _resp_get_status(field_varint(2, 3) + field_varint(10, 1))
CONNECTING = _resp_get_status(field_varint(2, 1))


def test_wifi_get_status_wire() -> None:
    # msg=0 (TypeCmdGetStatus) omitted; the empty arm (field 10) selects the command.
    assert wifi_get_status() == b"\x52\x00"


def test_parse_wifi_status_connected_with_ip() -> None:
    status = parse_wifi_status(CONNECTED)
    assert status is not None
    assert status.state is WifiStationState.CONNECTED
    assert status.ip4 == "192.168.2.41"
    assert status.fail_reason is None


def test_parse_wifi_status_auth_error() -> None:
    status = parse_wifi_status(AUTH_ERROR)
    assert status is not None
    assert status.state is WifiStationState.CONNECTION_FAILED
    assert status.fail_reason is WifiConnectFailedReason.AUTH_ERROR


def test_parse_wifi_status_network_not_found() -> None:
    status = parse_wifi_status(NETWORK_NOT_FOUND)
    assert status is not None
    assert status.state is WifiStationState.CONNECTION_FAILED
    assert status.fail_reason is WifiConnectFailedReason.NETWORK_NOT_FOUND


def test_parse_wifi_status_connecting() -> None:
    status = parse_wifi_status(CONNECTING)
    assert status is not None
    assert status.state is WifiStationState.CONNECTING


@pytest.mark.parametrize("response", [b"", field_varint(1, 3), _resp_get_status(b"")])
def test_parse_wifi_status_no_verdict(response: bytes) -> None:
    # Empty replies, non-status payloads, and a bare RespGetStatus (whose
    # all-defaults form is ambiguous with Connected) all read as "no verdict".
    assert parse_wifi_status(response) is None


@dataclass
class _FakeTransport:
    """Replays canned GetStatus responses; repeats the last one forever."""

    responses: list[bytes]
    requests: list[tuple[str, bytes]] = field(default_factory=list)

    async def request(self, endpoint: str, payload: bytes) -> bytes:
        self.requests.append((endpoint, payload))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def _run_verify(
    transport: _FakeTransport, monkeypatch: pytest.MonkeyPatch, *, wifi_wait: float = 0.2
) -> list[str]:
    monkeypatch.setattr(provision_module, "WIFI_POLL_INTERVAL", 0.0)
    monkeypatch.setattr(provision_module, "WIFI_SETTLE", 0.0)
    config = _config("LR4C123456")
    config.wifi_ssid = "IoT"
    config.wifi_wait = wifi_wait
    steps: list[str] = []
    asyncio.run(_verify_wifi(transport, config, steps.append))  # type: ignore[arg-type]
    return steps


def test_verify_wifi_returns_on_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport([CONNECTING, CONNECTED])
    steps = _run_verify(transport, monkeypatch)
    assert any("WiFi connected" in s and "192.168.2.41" in s for s in steps)
    assert all(endpoint == EP_PROV_CONFIG for endpoint, _ in transport.requests)


def test_verify_wifi_does_not_report_the_unset_address_as_a_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The robot answers CONNECTED as soon as the STA associates, before DHCP
    returns — a live re-provision printed `ip=0.0.0.0`. The join is confirmed,
    the address is not, and the step line must not claim otherwise."""
    connected_no_lease = _resp_get_status(
        field_message(11, field_string(1, "0.0.0.0") + field_varint(5, 6))
    )
    steps = _run_verify(_FakeTransport([connected_no_lease]), monkeypatch)
    assert any("WiFi connected" in s for s in steps), "the join is still confirmed"
    assert not any("0.0.0.0" in s for s in steps), "but the unset address is not a lease"


def test_verify_wifi_waits_for_the_lease_before_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The address arrives a beat after the association, and it is worth waiting for.

    The robot answers CONNECTED the moment the STA associates, so the first read
    always finds `0.0.0.0`. Reporting that first answer and returning threw away
    an address that was seconds away — and the address is the whole point: it is
    what tells you where the robot actually landed.
    """
    no_lease = _resp_get_status(
        field_message(11, field_string(1, "0.0.0.0") + field_varint(5, 6))
    )
    transport = _FakeTransport([no_lease, no_lease, CONNECTED])
    steps = _run_verify(transport, monkeypatch, wifi_wait=5.0)
    assert any("192.168.2.41" in s for s in steps), steps
    assert not any("no IP lease yet" in s for s in steps)


def test_verify_wifi_keeps_waiting_through_an_implausible_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed address that no robot on a LAN could hold must not end the wait.

    A live re-provision reported `ip=1.0.0.0` from a robot whose actual lease was a
    192.168 address. `1.0.0.0` is a valid public address, so every "is it 0.0.0.0"
    guard passes it — the wait ended on the first answer and the real lease, still
    seconds away, was never collected. Printing it also pointed the reader at an
    address the robot does not have.
    """
    bogus = _resp_get_status(
        field_message(11, field_string(1, "1.0.0.0") + field_varint(5, 6))
    )
    transport = _FakeTransport([bogus, bogus, CONNECTED])
    steps = _run_verify(transport, monkeypatch, wifi_wait=5.0)
    assert any("192.168.2.41" in s for s in steps), steps
    assert not any("1.0.0.0" in s for s in steps), "the implausible address is never shown"


def test_verify_wifi_says_nothing_about_a_lease_that_never_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No lease is our plumbing, not a fact about the robot.

    The join is confirmed either way, and a trailing "(no IP lease yet)" reads as a
    half-finished provision to somebody who has just watched thirteen steps succeed.
    """
    no_lease = _resp_get_status(
        field_message(11, field_string(1, "0.0.0.0") + field_varint(5, 6))
    )
    # The lease window has to be SHORTER than the total wait or the loop never
    # reaches its own give-up arm — it keeps polling until `wifi_wait` expires and
    # the post-loop fallback prints instead, leaving the in-loop line unpinned and a
    # revert of it green. At the shipped 20 s / 12 s that arm is what a real run hits.
    monkeypatch.setattr(provision_module, "WIFI_LEASE_WAIT", 0.0)
    steps = _run_verify(_FakeTransport([no_lease, no_lease]), monkeypatch, wifi_wait=5.0)
    assert any(s == "WiFi connected" for s in steps), steps
    assert not any("lease" in s for s in steps)


@pytest.mark.parametrize(
    "reported",
    [
        "0.0.0.0", "1.0.0.0", "169.254.10.4", "127.0.0.1", "8.8.8.8", "not-an-ip", "",
        # Every one of these is `is_private`, which is why membership is tested
        # against the three RFC 1918 ranges instead of that flag.
        "192.0.2.1", "198.51.100.1", "203.0.113.1", "240.0.0.1", "255.255.255.255",
        # Just outside 172.16/12 — the range whose boundary is easiest to get wrong.
        "172.32.0.1", "172.15.255.254",
    ],
)
def test_lan_address_rejects_what_a_robot_cannot_hold(reported: str) -> None:
    """169.254.x is the one that looks like a lease and is the opposite of one:
    it is what a client assigns itself when DHCP does NOT answer."""
    assert provision_module._lan_address(reported) is None


@pytest.mark.parametrize(
    "reported",
    ["192.168.3.30", "10.0.0.7", "172.16.4.9", "172.31.255.254", "172.16.0.1"],
)
def test_lan_address_accepts_a_private_lease(reported: str) -> None:
    assert provision_module._lan_address(reported) == reported


def test_verify_wifi_rides_out_a_gatt_hiccup(monkeypatch: pytest.MonkeyPatch) -> None:
    """One failed GetStatus is a radio hiccup, not a failed join. Treating it as
    fatal would abort a provision that was working, at the step immediately
    before the broker config is written."""

    class Flaky(_FakeTransport):
        def __init__(self) -> None:
            super().__init__([CONNECTED])
            self._first = True

        async def request(self, endpoint: str, payload: bytes) -> bytes:
            if self._first:
                self._first = False
                raise OSError("characteristic read failed")
            return await super().request(endpoint, payload)

    steps = _run_verify(Flaky(), monkeypatch)
    assert any("WiFi connected" in s for s in steps), "the join is still confirmed"


def test_verify_wifi_raises_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport([CONNECTING, AUTH_ERROR])
    with pytest.raises(ProvisioningError, match="mistyped WiFi password"):
        _run_verify(transport, monkeypatch)


def test_verify_wifi_raises_on_network_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport([NETWORK_NOT_FOUND])
    with pytest.raises(ProvisioningError, match="'IoT' not found"):
        _run_verify(transport, monkeypatch)


def test_verify_wifi_silent_firmware_degrades_to_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    # A firmware that never answers GetStatus must not fail a good join: the
    # verify runs out the clock, warns, and provisioning continues as before.
    transport = _FakeTransport([b""])
    steps = _run_verify(transport, monkeypatch)
    assert any("no WiFi status" in s for s in steps)


def test_verify_wifi_still_connecting_warns_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport([CONNECTING])
    steps = _run_verify(transport, monkeypatch)
    assert any("still connecting" in s for s in steps)
