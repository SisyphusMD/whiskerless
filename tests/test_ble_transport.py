"""The BLE transport, faked at the bleak boundary.

Provisioning is the one irreversible thing this project does — it re-points the
robot away from Whisker's cloud, and getting it wrong costs a BLE re-provision to
undo — so the sequencing deserves tests even though the radio cannot be faked.

What is asserted is protocol shape: which characteristic a request goes to, that
a response is read back from the same one, and that a dry run writes nothing.
Whether the robot on the bench agrees is a bench question, not a test one.
"""

from __future__ import annotations

import logging
from inspect import signature
from types import SimpleNamespace
from typing import Any, ClassVar
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


class FakeScanner:
    """A BleakScanner that hands its advertisements to the detection callback.

    The real scan now returns on the first answer instead of running its window
    out, so the fake has to deliver detections the same way — through the
    callback at ``start()`` — rather than returning a dict at the end.
    """

    result: ClassVar[dict[str, tuple[FakeDevice, FakeAdv]]] = {}
    starts = 0

    def __init__(self, detection_callback: Any = None, **_: object) -> None:
        self._cb = detection_callback

    async def start(self) -> None:
        type(self).starts += 1
        for device, adv in self.result.values():
            if self._cb is not None:
                self._cb(device, adv)

    async def stop(self) -> None:
        return None


def _scanner(result: dict[str, tuple[FakeDevice, FakeAdv]]) -> Any:
    FakeScanner.result = result
    FakeScanner.starts = 0
    return patch("bleak.BleakScanner", FakeScanner)


async def test_a_robot_is_matched_by_its_protocomm_service_uuid() -> None:
    """The advertised name is intermittent; the service UUID is not."""
    found = {"a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID.upper()]))}
    with _scanner(found):
        assert await scan(timeout=0, rounds=1, settle=0) == [DiscoveredRobot("AA:01", "?", -60)]


async def test_a_robot_is_also_matched_by_the_advertised_name() -> None:
    found = {"a": (FakeDevice("AA:01"), FakeAdv(local_name=ADVERTISER_NAME))}
    with _scanner(found):
        assert (await scan(timeout=0, rounds=1, settle=0))[0].address == "AA:01"


async def test_results_are_ordered_by_signal_so_the_nearest_is_first() -> None:
    """With several robots in a house, closest is the one you are standing at."""
    found = {
        "far": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-90)),
        "near": (FakeDevice("AA:02"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-40)),
    }
    with _scanner(found):
        assert [r.address for r in await scan(timeout=0, rounds=1, settle=0)] == ["AA:02", "AA:01"]


async def test_an_explicit_address_returns_that_robot_even_unmatched() -> None:
    """Firmware that advertises neither marker still has to be reachable."""
    found = {"a": (FakeDevice("AA:01"), FakeAdv())}
    with _scanner(found):
        assert (await scan(timeout=0, rounds=1, address="aa:01", settle=0))[0].address == "AA:01"


async def test_nothing_advertising_is_an_empty_list_not_an_error() -> None:
    """The LR4 advertises sporadically, so an empty round is ordinary."""
    with _scanner({}):
        assert await scan(timeout=0, rounds=2, settle=0) == []


async def test_a_characteristic_without_a_name_descriptor_is_skipped() -> None:
    """Only protocomm endpoints carry a 0x2901; the rest are ordinary GATT."""

    class Mixed(FakeBleakClient):
        def __init__(self) -> None:
            super().__init__({1: b"prov-session"})
            self.services[0].characteristics.append(FakeChar("plain", []))

    assert sorted(await ProtocommBLE(Mixed()).discover_endpoints()) == ["prov-session"]


async def test_the_scan_retries_before_giving_up() -> None:
    """The LR4 advertises sporadically; one empty round proves nothing."""

    class Retrying(FakeScanner):
        async def start(self) -> None:
            type(self).starts += 1
            if type(self).starts < 2:
                return
            self._cb(FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID]))

    Retrying.starts = 0
    with patch("bleak.BleakScanner", Retrying):
        assert (await scan(timeout=0, rounds=3, settle=0))[0].address == "AA:01"
    assert Retrying.starts == 2


async def test_the_scan_stops_at_the_first_answer_instead_of_running_the_window_out() -> None:
    """``timeout`` is a ceiling, not a duration: the scan returns as soon as a
    robot answers, however long the caller was willing to wait."""
    found = {"a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID]))}
    with _scanner(found):
        # A timeout of an hour must not be waited on when the robot answers now.
        assert (await scan(timeout=3600, rounds=1, settle=0))[0].address == "AA:01"


async def test_a_device_that_is_not_an_lr4_is_ignored() -> None:
    """A house is full of advertising Bluetooth; only protocomm answers count."""
    found = {"tv": (FakeDevice("BB:02", "Living Room TV"), FakeAdv(uuids=["1234"]))}
    with _scanner(found):
        assert await scan(timeout=0, rounds=1, settle=0) == []


async def test_an_address_targeted_scan_does_not_wait_to_settle() -> None:
    """Only one device can match an address, so there is nothing to wait for."""
    import asyncio

    found = {"a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID]))}
    with _scanner(found):
        # A settle of half a minute must not be honoured; if it is, this times out.
        robots = await asyncio.wait_for(
            scan(timeout=0, rounds=1, address="aa:01", settle=30), timeout=2
        )
    assert [r.address for r in robots] == ["AA:01"]


async def test_an_explicit_address_ignores_every_other_robot() -> None:
    """--address exists to pick ONE robot out of several in range."""
    found = {
        "other": (FakeDevice("BB:02"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-40)),
        "wanted": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-90)),
    }
    with _scanner(found):
        robots = await scan(timeout=0, rounds=1, address="aa:01", settle=0)
    assert [r.address for r in robots] == ["AA:01"], "the nearer robot must not win"


async def test_the_settle_window_still_collects_a_second_robot() -> None:
    """Returning on the FIRST answer would let whichever robot replied first win
    a race, and a house with two of them would silently only be offered one."""
    found = {
        "a": (FakeDevice("AA:01"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-90)),
        "b": (FakeDevice("AA:02"), FakeAdv(uuids=[PROV_SERVICE_UUID], rssi=-40)),
    }
    with _scanner(found):
        robots = await scan(timeout=0, rounds=1, settle=0.01)
    assert [r.address for r in robots] == ["AA:02", "AA:01"]


async def test_a_bluetooth_failure_is_a_sentence_not_a_stack_trace() -> None:
    """The CLI cannot catch BleakError itself — bleak is the optional [ble]
    extra, so importing it just to name an exception type would put a Bluetooth
    stack behind every non-BLE command. Translation belongs at this boundary."""
    import bleak

    class Broken(FakeScanner):
        async def start(self) -> None:
            raise bleak.exc.BleakError("Bluetooth device is turned off")

    with patch("bleak.BleakScanner", Broken), pytest.raises(ProvisioningError) as err:
        await scan(timeout=0, rounds=1, settle=0)

    assert "BLE scan failed" in str(err.value), "and it says what was being attempted"
    assert "Bluetooth device is turned off" in str(err.value), "keeping what bleak knew"


# --- the callback bleak will actually accept ----------------------------------------
#
# The one thing in this file a FAKE can never check, and skipping it shipped a
# broken provisioner. The detection callback carried its per-round state as default
# arguments, which makes it FOUR parameters, and bleak refuses anything but two —
# so every 0.2.0 candidate reached "scanning for robots over BLE ..." and then died
# on `TypeError: callback must be callable with 2 parameters`. That is true on
# 0.22.0, the declared floor, as well as on current bleak, so no supported version
# of this could have worked.
#
# It calls bleak's OWN validator rather than restating the rule — the rule is
# bleak's to change — and needs no radio: the signature is inspected before any
# backend is touched.
async def test_the_detection_callback_is_one_bleak_accepts() -> None:
    scanner_module = pytest.importorskip("bleak.backends.scanner")
    captured: list[Any] = []

    class ValidatingScanner(FakeScanner):
        def __init__(self, detection_callback: Any = None, **kw: object) -> None:
            captured.append(detection_callback)
            scanner_module.BaseBleakScanner.register_detection_callback(
                SimpleNamespace(_ad_callbacks={}), detection_callback
            )
            super().__init__(detection_callback=detection_callback, **kw)

    FakeScanner.result = {"a": (FakeDevice("AA:01"), FakeAdv(local_name=ADVERTISER_NAME))}
    with patch("bleak.BleakScanner", ValidatingScanner):
        assert (await scan(timeout=0, rounds=1, settle=0))[0].address == "AA:01"

    assert captured, "the scan never built a detection callback"
    parameters = signature(captured[0]).parameters
    assert len(parameters) == 2, (
        f"bleak accepts exactly two parameters; this takes {len(parameters)}: {list(parameters)}"
    )


async def test_each_round_gets_its_own_detection_callback() -> None:
    """Why the callback is built by a factory rather than defined in the loop.

    A callback outlives the round that made it, so a late advertisement must land
    in the results of the round it belongs to and not the next one. Binding the
    per-round state as default arguments is the usual way to get that lifetime,
    and it is exactly what bleak rejects."""
    callbacks: list[Any] = []

    class RecordingScanner(FakeScanner):
        def __init__(self, detection_callback: Any = None, **kw: object) -> None:
            callbacks.append(detection_callback)
            super().__init__(detection_callback=detection_callback, **kw)

    FakeScanner.result = {}
    with patch("bleak.BleakScanner", RecordingScanner):
        assert await scan(timeout=0, rounds=3, settle=0) == []
    assert len(callbacks) == 3
    assert len(set(map(id, callbacks))) == 3, "rounds shared a callback"


async def test_a_machine_with_no_bluetooth_gets_a_sentence_not_a_traceback() -> None:
    """The BlueZ backend does not always fail as a BleakError.

    With no D-Bus at all — a container, a headless box with bluetooth masked, a Pi
    whose service never started — it fails on the socket and raises a bare
    FileNotFoundError, which reached the user as a traceback."""

    class NoBluetooth(FakeScanner):
        async def start(self) -> None:
            raise FileNotFoundError(2, "No such file or directory")

    FakeScanner.result = {}
    with patch("bleak.BleakScanner", NoBluetooth), pytest.raises(ProvisioningError) as caught:
        await scan(timeout=0, rounds=1, settle=0)
    assert "no usable Bluetooth" in str(caught.value)
    assert "Bluetooth service is running" in str(caught.value)


async def test_a_dropped_link_is_not_blamed_on_the_adapter() -> None:
    """`translated` wraps whole provisioning sessions, not just the scan.

    A robot that drops the link mid-write also surfaces as an OSError, and telling
    somebody to check an adapter that is working sends them to the wrong place —
    so only the errors that mean "the backend is not reachable" get that advice."""

    class DroppedLink(FakeScanner):
        async def start(self) -> None:
            raise ConnectionResetError(104, "Connection reset by peer")

    FakeScanner.result = {}
    with patch("bleak.BleakScanner", DroppedLink), pytest.raises(ProvisioningError) as caught:
        await scan(timeout=0, rounds=1, settle=0)
    assert "Connection reset by peer" in str(caught.value)
    assert "adapter is present" not in str(caught.value)


async def test_credentials_never_reach_the_request_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`--debug` now switches the request log on, and its help calls that log the
    thing to attach to a bug report — so what it prints matters.

    Two endpoints must never show a payload: `prov-config` carries the WiFi
    passphrase in cleartext, and `mqtt-config` carries the robot's PRIVATE KEY in
    CERT_WRITE chunks. `prov-scan` must still show one, because that hex is what
    a real paging bug was found in.
    """
    secret = b"hunter2-and-a-private-key"
    client = FakeBleakClient({1: b"prov-config", 2: b"mqtt-config", 3: b"prov-scan"})
    transport = ProtocommBLE(client)
    await transport.discover_endpoints()

    for endpoint, expect_hex in (("prov-config", False), ("mqtt-config", False), ("prov-scan", True)):
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="whiskerless.ble.transport"):
            await transport.request(endpoint, secret)
        logged = caplog.text
        if expect_hex:
            assert secret.hex() in logged, "the half of the log that finds bugs is gone"
        else:
            assert secret.hex() not in logged, f"{endpoint} leaked its payload"
            assert "redacted" in logged

