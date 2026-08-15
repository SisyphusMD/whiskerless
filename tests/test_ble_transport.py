"""The BLE transport, faked at the bleak boundary.

Provisioning is the one irreversible thing this project does — it re-points the
robot away from Whisker's cloud, and getting it wrong costs a BLE re-provision to
undo — so the sequencing deserves tests even though the radio cannot be faked.

What is asserted is protocol shape: which characteristic a request goes to, that
a response is read back from the same one, and that a dry run writes nothing.
Whether the robot on the bench agrees is a bench question, not a test one.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from whiskerless.ble.messages import ADVERTISER_NAME, PROV_SERVICE_UUID
from whiskerless.ble.transport import USER_DESC_UUID, DiscoveredRobot, ProtocommBLE, scan
from whiskerless.exceptions import ProvisioningError


class FakeDescriptor:
    def __init__(self, uuid: str, handle: int) -> None:
        self.uuid = uuid
        self.handle = handle


class FakeChar:
    def __init__(self, uuid: str, descriptors: list[FakeDescriptor]) -> None:
        self.uuid = uuid
        self.descriptors = descriptors


class FakeService:
    def __init__(self, characteristics: list[FakeChar]) -> None:
        self.characteristics = characteristics


class FakeBleakClient:
    """Enough of a BleakClient for the protocomm request/response shape."""

    def __init__(self, names: dict[int, bytes], *, read_fails: bool = False) -> None:
        self.services = [
            FakeService(
                [
                    FakeChar(f"char-{handle}", [FakeDescriptor(USER_DESC_UUID, handle)])
                    for handle in names
                ]
            )
        ]
        self._names = names
        self._read_fails = read_fails
        self.writes: list[tuple[Any, bytes]] = []
        self.response = b"\x01\x02"

    async def read_gatt_descriptor(self, handle: int) -> bytes:
        if self._read_fails:
            import bleak

            raise bleak.exc.BleakError("descriptor unreadable")
        return self._names[handle]

    async def write_gatt_char(self, char: Any, payload: bytes, response: bool = True) -> None:
        self.writes.append((char, payload))

    async def read_gatt_char(self, char: Any) -> bytes:
        return self.response


bleak = pytest.importorskip("bleak", reason="the BLE extra is bench-only")


async def test_endpoints_are_named_by_their_user_description() -> None:
    """protocomm identifies endpoints by the 0x2901 descriptor, not the UUID."""
    client = FakeBleakClient({1: b"prov-session", 2: b"custom-data"})
    endpoints = await ProtocommBLE(client).discover_endpoints()
    assert sorted(endpoints) == ["custom-data", "prov-session"]


async def test_a_null_padded_description_is_trimmed() -> None:
    """GATT pads to the characteristic length; the tail is not part of the name."""
    client = FakeBleakClient({1: b"prov-session\x00\x00\x00"})
    assert "prov-session" in await ProtocommBLE(client).discover_endpoints()


async def test_a_descriptor_that_will_not_read_is_skipped_not_fatal() -> None:
    """One unreadable characteristic must not abandon the whole discovery."""
    client = FakeBleakClient({1: b"prov-session"}, read_fails=True)
    assert await ProtocommBLE(client).discover_endpoints() == {}


async def test_a_request_writes_then_reads_the_same_characteristic() -> None:
    client = FakeBleakClient({1: b"prov-session"})
    transport = ProtocommBLE(client)
    await transport.discover_endpoints()

    client.response = b"\xaa\xbb"
    assert await transport.request("prov-session", b"\x01") == b"\xaa\xbb"
    assert len(client.writes) == 1


async def test_an_unknown_endpoint_names_what_was_discovered() -> None:
    """The failure a wrong firmware produces, so it has to say what it did find."""
    client = FakeBleakClient({1: b"prov-session"})
    transport = ProtocommBLE(client)
    await transport.discover_endpoints()

    with pytest.raises(ProvisioningError, match="prov-session"):
        await transport.request("prov-config", b"\x01")


async def test_a_dry_run_writes_nothing_to_the_robot() -> None:
    """The whole point of --dry-run: exercise the flow without re-pointing it."""
    client = FakeBleakClient({1: b"prov-session"})
    transport = ProtocommBLE(client, dry_run=True)
    await transport.discover_endpoints()

    assert await transport.request("prov-session", b"\x01") == b""
    assert client.writes == []


# --- scanning ----------------------------------------------------------------
class FakeDevice:
    def __init__(self, address: str, name: str | None = None) -> None:
        self.address = address
        self.name = name


class FakeAdv:
    def __init__(
        self, local_name: str | None = None, uuids: list[str] | None = None, rssi: int = -60
    ) -> None:
        self.local_name = local_name
        self.service_uuids = uuids
        self.rssi = rssi


def _scanner(result: dict[str, tuple[FakeDevice, FakeAdv]]) -> Any:
    async def _discover(**_: object) -> dict[str, tuple[FakeDevice, FakeAdv]]:
        return result

    return patch("bleak.BleakScanner.discover", _discover)


async def test_a_robot_is_matched_by_its_protocomm_service_uuid() -> None:
    """The advertised name is intermittent; the service UUID is not."""
    found = {"a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID.upper()]))}
    with _scanner(found):
        assert await scan(timeout=0, rounds=1) == [DiscoveredRobot("AA:01", "?", -60)]


async def test_a_robot_is_also_matched_by_the_advertised_name() -> None:
    found = {"a": (FakeDevice("AA:01"), FakeAdv(local_name=ADVERTISER_NAME))}
    with _scanner(found):
        assert (await scan(timeout=0, rounds=1))[0].address == "AA:01"


async def test_results_are_ordered_by_signal_so_the_nearest_is_first() -> None:
    """With several robots in a house, closest is the one you are standing at."""
    found = {
        "far": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-90)),
        "near": (FakeDevice("AA:02"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-40)),
    }
    with _scanner(found):
        assert [r.address for r in await scan(timeout=0, rounds=1)] == ["AA:02", "AA:01"]


async def test_an_explicit_address_returns_that_robot_even_unmatched() -> None:
    """Firmware that advertises neither marker still has to be reachable."""
    found = {"a": (FakeDevice("AA:01"), FakeAdv())}
    with _scanner(found):
        assert (await scan(timeout=0, rounds=1, address="aa:01"))[0].address == "AA:01"


async def test_nothing_advertising_is_an_empty_list_not_an_error() -> None:
    """The LR4 advertises sporadically, so an empty round is ordinary."""
    with _scanner({}):
        assert await scan(timeout=0, rounds=2) == []


async def test_a_characteristic_without_a_name_descriptor_is_skipped() -> None:
    """Only protocomm endpoints carry a 0x2901; the rest are ordinary GATT."""

    class Mixed(FakeBleakClient):
        def __init__(self) -> None:
            super().__init__({1: b"prov-session"})
            self.services[0].characteristics.append(FakeChar("plain", []))

    assert sorted(await ProtocommBLE(Mixed()).discover_endpoints()) == ["prov-session"]


async def test_the_scan_retries_before_giving_up() -> None:
    """The LR4 advertises sporadically; one empty round proves nothing."""
    rounds = 0

    async def _discover(**_: object) -> dict[str, Any]:
        nonlocal rounds
        rounds += 1
        if rounds < 2:
            return {}
        return {"a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID]))}

    with patch("bleak.BleakScanner.discover", _discover):
        assert (await scan(timeout=0, rounds=3))[0].address == "AA:01"
    assert rounds == 2


async def test_a_bluetooth_failure_is_a_sentence_not_a_stack_trace() -> None:
    """The CLI cannot catch BleakError itself — bleak is the optional [ble]
    extra, so importing it just to name an exception type would put a Bluetooth
    stack behind every non-BLE command. Translation belongs at this boundary."""
    import bleak

    async def _discover(**_: object) -> dict[str, Any]:
        raise bleak.exc.BleakError("Bluetooth device is turned off")

    with patch("bleak.BleakScanner.discover", _discover), pytest.raises(ProvisioningError) as err:
        await scan(timeout=0, rounds=1)

    assert "BLE scan failed" in str(err.value), "and it says what was being attempted"
    assert "Bluetooth device is turned off" in str(err.value), "keeping what bleak knew"
