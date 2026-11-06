"""Ask a robot's protocomm `proto-ver` endpoint for its version and security level.

The endpoint answers any write with a JSON capability list, e.g.
``{"prov": {"cap": "no_sec,no_pop,wifi_scan"}}``; ``no_sec`` means every later
provisioning write, private key included, travels in cleartext. The write changes
no state on the robot.

usage: python scripts/ble_protover.py NAME_OR_ADDRESS      (needs the `ble` extra: bleak)
"""
from __future__ import annotations

import asyncio
import sys

from ble_gatt import find
from bleak import BleakClient

USER_DESCRIPTION = "00002901-0000-1000-8000-00805f9b34fb"


async def main(target: str) -> None:
    async with BleakClient(await find(target), timeout=30) as client:
        for service in client.services:
            for char in service.characteristics:
                for desc in char.descriptors:
                    if desc.uuid.lower() != USER_DESCRIPTION:
                        continue
                    if bytes(await client.read_gatt_descriptor(desc.handle)) == b"proto-ver":
                        await client.write_gatt_char(char, b"---", response=True)
                        reply = bytes(await client.read_gatt_char(char))
                        print(reply.decode(errors="replace"))
                        return
    raise SystemExit("no proto-ver endpoint found")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <name-or-address>")
    asyncio.run(main(sys.argv[1]))
