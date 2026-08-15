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
