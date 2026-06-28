"""BLE protocomm transport over GATT (bleak).

Each protocomm endpoint is a GATT characteristic named via its 0x2901 user
description; a request is a write and the response is a read-back on the same
characteristic. Robots are matched by their protocomm *service UUID* rather than
the weak, intermittent advertised name.

``bleak`` is an optional dependency (``pip install whiskerless[ble]``); it is
imported lazily so the rest of the library works without it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..exceptions import ProvisioningError
from .messages import ADVERTISER_NAME, PROV_SERVICE_UUID

if TYPE_CHECKING:
    from bleak import BleakClient

log = logging.getLogger(__name__)

USER_DESC_UUID = "00002901-0000-1000-8000-00805f9b34fb"


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
) -> list[DiscoveredRobot]:
    """Scan for advertising LR4s, matched by protocomm service UUID (or name).

    The LR4 advertises sporadically at low RSSI, so the scan retries a few
    rounds. If ``address`` is given, only that device is returned (when seen).
    """
    bleak = _require_bleak()
    target = PROV_SERVICE_UUID.lower()
    for attempt in range(1, max(1, rounds) + 1):
        log.info("scanning %.0fs for LR4 (attempt %d/%d)", timeout, attempt, rounds)
        discovered = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
        matches: list[DiscoveredRobot] = []
        for device, adv in discovered.values():
            name = adv.local_name or device.name or ""
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            if address and device.address.lower() == address.lower():
                return [DiscoveredRobot(device.address, name or "?", adv.rssi)]
            if target in uuids or name == ADVERTISER_NAME:
                matches.append(DiscoveredRobot(device.address, name or "?", adv.rssi))
        if matches:
            matches.sort(key=lambda r: r.rssi or -999, reverse=True)
            return matches
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
