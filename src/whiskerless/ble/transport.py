"""BLE protocomm transport over GATT (bleak).

Each protocomm endpoint is a GATT characteristic named via its 0x2901 user
description; a request is a write and the response is a read-back on the same
characteristic. Robots are matched by their protocomm *service UUID* rather than
the weak, intermittent advertised name.

``bleak`` is an optional dependency (``pip install whiskerless[ble]``); it is
imported lazily so the rest of the library works without it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..exceptions import ProvisioningError
from .messages import ADVERTISER_NAME, PROV_SERVICE_UUID

if TYPE_CHECKING:
    from bleak import BleakClient

log = logging.getLogger(__name__)

USER_DESC_UUID = "00002901-0000-1000-8000-00805f9b34fb"


@contextlib.asynccontextmanager
async def translated(action: str) -> AsyncIterator[None]:
    """Turn a bleak failure into a ProvisioningError naming what was happening.

    The CLI cannot catch `BleakError` itself: bleak is the optional `[ble]`
    extra, so importing it unconditionally to name an exception type would make
    every non-BLE command depend on it. Translation therefore belongs here, at
    the boundary that already knows bleak is present — the same way the MQTT
    link wraps its connect errors instead of letting aiomqtt's reach a user.
    """
    bleak = _require_bleak()
    try:
        yield
    except bleak.exc.BleakError as exc:
        # Bleak's messages are terse and context-free ("Bluetooth device is
        # turned off"), so the action is what makes them actionable.
        raise ProvisioningError(f"{action}: {exc}") from exc
    except (FileNotFoundError, ConnectionRefusedError, PermissionError) as exc:
        # Not every unusable radio arrives as a BleakError. With no D-Bus at all —
        # a container, a headless box with bluetooth masked, a Pi whose service
        # never started — the BlueZ backend fails on the SOCKET and raises a bare
        # OSError, which reached the user as a traceback from the one command that
        # cannot be casually retried: the robot only advertises while somebody is
        # holding its button.
        #
        # Only the three that mean "the backend is not reachable". This wraps whole
        # provisioning sessions, not just the scan, so a robot dropping the link
        # mid-write must not be reported as a missing adapter — that sends someone
        # to check hardware that is working.
        raise ProvisioningError(
            f"{action}: no usable Bluetooth on this machine ({exc}). Check that an "
            f"adapter is present and the Bluetooth service is running."
        ) from exc
    except OSError as exc:
        # Anything else the radio stack raises still has to be a sentence; it just
        # gets the plain form, named for whatever was being attempted.
        raise ProvisioningError(f"{action}: {exc}") from exc


def _require_bleak() -> Any:
    try:
        import bleak
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ProvisioningError(
            "BLE provisioning needs the 'ble' extra: pip install 'whiskerless[ble]'"
        ) from exc
    return bleak


@dataclass(frozen=True, slots=True)
class DiscoveredRobot:
    """A robot seen during a BLE scan."""

    address: str
    name: str
    rssi: int | None


async def scan(
    *,
    timeout: float = 15.0,
    rounds: int = 3,
    address: str | None = None,
    settle: float = 1.5,
) -> list[DiscoveredRobot]:
    """Scan for advertising LR4s, matched by protocomm service UUID (or name).

    ``timeout`` is a CEILING, not a duration: the scan returns as soon as a
    robot answers. This is not just about feeling quick — a robot only
    advertises while it is in pairing mode, and a scan that always runs its
    window out spends the pairing window rather than using it. A bench session
    lost a window exactly that way, discovering the robot and then failing to
    connect because it had stopped advertising by the time the scan ended.

    ``settle`` keeps listening for a beat after the first answer, so a second
    robot advertising in the same window is still offered rather than silently
    losing a race to whichever replied first.

    The LR4 advertises sporadically at low RSSI, so an empty round is retried.
    If ``address`` is given, only that device is returned (when seen).
    """
    bleak = _require_bleak()
    target = PROV_SERVICE_UUID.lower()

    def _detector(
        _found: dict[str, DiscoveredRobot], _answered: asyncio.Event
    ) -> Callable[[Any, Any], None]:
        """Build this round's detection callback.

        A FACTORY, and it has to be. The per-round objects must be bound to the
        round that made them — the callback outlives its iteration, and a late
        advertisement must not land in the next round's results — but bleak
        inspects the callback and raises `callback must be callable with 2
        parameters` unless it takes exactly two. Binding them as default
        arguments, which is the other way to get the same lifetime, makes it four
        and the scan cannot start at all. Closing over the factory's parameters
        gives both properties at once.
        """

        def _detected(device: Any, adv: Any) -> None:
            name = adv.local_name or device.name or ""
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            if address is not None:
                if device.address.lower() != address.lower():
                    return
            elif target not in uuids and name != ADVERTISER_NAME:
                return
            _found[device.address] = DiscoveredRobot(device.address, name or "?", adv.rssi)
            _answered.set()

        return _detected

    for attempt in range(1, max(1, rounds) + 1):
        log.info("scanning up to %.0fs for LR4 (attempt %d/%d)", timeout, attempt, rounds)
        found: dict[str, DiscoveredRobot] = {}
        answered = asyncio.Event()

        async with translated("BLE scan failed"):
            scanner = bleak.BleakScanner(detection_callback=_detector(found, answered))
            await scanner.start()
            try:
                if not answered.is_set():
                    await asyncio.wait_for(answered.wait(), timeout)
                # Only worth settling when there is something else to collect.
                # An address-targeted scan can match exactly one device, so
                # waiting would spend the pairing window it exists to save.
                if settle > 0 and address is None:
                    await asyncio.sleep(settle)
            except TimeoutError:
                pass
            finally:
                await scanner.stop()
        if found:
            return sorted(found.values(), key=lambda r: r.rssi or -999, reverse=True)
    return []


class ProtocommBLE:
    """A protocomm-over-GATT client bound to one connected BleakClient."""

    def __init__(self, client: BleakClient, *, dry_run: bool = False) -> None:
        self._client = client
        self._dry_run = dry_run
        self._endpoints: dict[str, Any] = {}

    async def discover_endpoints(self) -> dict[str, Any]:
        """Map protocomm endpoint name → characteristic via 0x2901 descriptors."""
        bleak = _require_bleak()
        found: dict[str, Any] = {}
        for service in self._client.services:
            for char in service.characteristics:
                desc = next(
                    (d for d in char.descriptors if d.uuid.lower() == USER_DESC_UUID), None
                )
                if desc is None:
                    continue
                try:
                    raw = await self._client.read_gatt_descriptor(desc.handle)
                except bleak.exc.BleakError as exc:
                    log.debug("descriptor read failed on %s: %s", char.uuid, exc)
                    continue
                name = bytes(raw).split(b"\x00", 1)[0].decode("utf-8", "replace")
                if name:
                    found[name] = char
        self._endpoints = found
        return found

    async def request(self, endpoint: str, payload: bytes) -> bytes:
        """Write a request to an endpoint and read back its response."""
        char = self._endpoints.get(endpoint)
        if char is None:
            raise ProvisioningError(
                f"endpoint {endpoint!r} not found; discovered {sorted(self._endpoints)}"
            )
        log.debug("→ %s (%d bytes) %s", endpoint, len(payload), payload.hex())
        if self._dry_run:
            return b""
        await self._client.write_gatt_char(char, payload, response=True)
        response = bytes(await self._client.read_gatt_char(char))
        log.debug("← %s (%d bytes) %s", endpoint, len(response), response.hex())
        return response
