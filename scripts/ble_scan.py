"""Passive BLE scan for Whisker robots: lists advertisers, flags protocomm services.

Listens only; sends nothing. A robot advertises its provisioning service in
pairing mode, and not reliably while connected to a broker.

usage: python scripts/ble_scan.py [SECONDS]      (needs the `ble` extra: bleak)
"""
from __future__ import annotations

import asyncio
import sys

from bleak import BleakScanner

SERVICES = {
    "b7ee1c20-dcfd-4208-8813-14845cac5212": "Litter-Robot 4",
    "28cbfd44-6c8c-43c4-88ee-4da18ca98510": "Litter-Robot EVO",
}
NAME_HINTS = ("litter", "whisker")


async def main(seconds: float) -> None:
    seen: dict[str, tuple[str, int, list[str]]] = {}

    def on_advert(device, adv) -> None:
        name = adv.local_name or device.name or ""
        best = seen.get(device.address)
        if best is None or adv.rssi > best[1]:
            seen[device.address] = (name, adv.rssi, [u.lower() for u in adv.service_uuids])

    async with BleakScanner(on_advert):
        await asyncio.sleep(seconds)
    found = 0
    for address, (name, rssi, uuids) in sorted(seen.items(), key=lambda kv: -kv[1][1]):
        robots = [SERVICES[u] for u in uuids if u in SERVICES]
        if robots or any(hint in name.lower() for hint in NAME_HINTS):
            found += 1
            label = f"  protocomm: {', '.join(robots)}" if robots else ""
            print(f"{address}  {name!r}  rssi {rssi}{label}")
    print(f"{found} Whisker advertiser(s) among {len(seen)}")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 60))
