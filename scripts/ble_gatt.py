"""Read-only GATT survey of a Whisker robot: services, characteristics, endpoint labels.

Connects, reads every descriptor (protocomm labels each endpoint with a 0x2901
user description), and disconnects. Never writes a characteristic.

usage: python scripts/ble_gatt.py NAME_OR_ADDRESS      (needs the `ble` extra: bleak)
       e.g. LitterRobot4, LitterRobotEvo, or a BLE address from ble_scan.py
"""
from __future__ import annotations

import asyncio
import sys

from bleak import BleakClient, BleakScanner


async def find(target: str):
    def match(device, adv) -> bool:
        name = adv.local_name or device.name or ""
        return target.lower() in (name.lower(), device.address.lower())

    device = await BleakScanner.find_device_by_filter(match, timeout=60)
    if device is None:
        raise SystemExit(f"{target} not found in 60 s (is the robot in pairing mode?)")
    return device


async def main(target: str) -> None:
    async with BleakClient(await find(target), timeout=30) as client:
        for service in client.services:
            print(f"service {service.uuid}")
            for char in service.characteristics:
                labels = []
                for desc in char.descriptors:
                    try:
                        raw = bytes(await client.read_gatt_descriptor(desc.handle))
                        labels.append(f"{desc.uuid[4:8]}={raw!r}")
                    except Exception as exc:  # noqa: BLE001 - report and keep surveying
                        labels.append(f"{desc.uuid[4:8]}=<{type(exc).__name__}>")
                print(f"  char {char.uuid}  props={','.join(char.properties)}  {'  '.join(labels)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <name-or-address>")
    asyncio.run(main(sys.argv[1]))
