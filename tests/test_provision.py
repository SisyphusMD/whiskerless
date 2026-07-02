"""Provisioning guards — LR4-only serial validation and the GATT model check."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from whiskerless.ble.messages import PROV_SERVICE_UUID
from whiskerless.ble.provision import ProvisioningConfig, _assert_lr4
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
