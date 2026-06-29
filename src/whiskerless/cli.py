"""whiskerless command-line interface.

A friendly front-end over the library: re-provision a robot onto your broker,
watch its telemetry, read/decode its state, and change settings (with read-back
verify). Every send goes through the safety guard, so the CLI cannot fire a
brick/reset-class command.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from typing import cast

from .ble.transport import DiscoveredRobot
from .devices.litter_robot_4 import commands, const
from .devices.litter_robot_4.commands import Command
from .devices.litter_robot_4.link import LitterRobot4Link
from .devices.litter_robot_4.protocol import ActivityMessage, StateMessage
from .exceptions import SafetyError, WhiskerlessError
from .mqtt import MqttSettings
from .safety import classify_code

log = logging.getLogger("whiskerless")

_REGISTER_NAMES = {int(r): r.name.lower() for r in const.Register}


# --- connection helpers ------------------------------------------------------
def _settings(args: argparse.Namespace) -> MqttSettings:
    return MqttSettings(
        host=args.host,
        port=args.port,
        ca_cert_path=args.ca,
        verify_hostname=not args.insecure,
        username=args.username,
        password=args.password,
        client_id=args.client_id,
    )


def _link(args: argparse.Namespace, *, subscribe: bool = True) -> LitterRobot4Link:
    return LitterRobot4Link(_settings(args), args.serial, subscribe=subscribe)


# --- command handlers --------------------------------------------------------
async def _cmd_monitor(args: argparse.Namespace) -> int:
    print(f"monitoring {args.serial} for {args.duration:.0f}s (ctrl-c to stop)…", flush=True)
    async with _link(args) as link:
        try:
            async with asyncio.timeout(args.duration):
                async for message in link.messages():
                    _print_message(message)
        except TimeoutError:
            pass
    return 0


async def _cmd_state(args: argparse.Namespace) -> int:
    async with _link(args) as link:
        await link.request_state()
        try:
            async with asyncio.timeout(args.timeout):
                async for message in link.messages():
                    if isinstance(message, StateMessage):
                        _print_state(message)
                        return 0
        except TimeoutError:
            print("no state document received (is the robot online?)", file=sys.stderr)
            return 1
    return 1


async def _cmd_read(args: argparse.Namespace) -> int:
    register = _parse_int(args.register)
    async with _link(args) as link:
        value = await link.read_register(register, timeout=args.timeout)
    name = _REGISTER_NAMES.get(register, "?")
    if value is None:
        print(f"register 0x{register:02X} ({name}): no echo (timeout)", file=sys.stderr)
        return 1
    print(f"register 0x{register:02X} ({name}) = {value} (0x{value:04X})")
    return 0


async def _cmd_set(args: argparse.Namespace) -> int:
    command = _build_setting(args.setting, args.value)
    async with _link(args) as link:
        ok = await link.apply_setting(command, retries=args.retries, timeout=args.timeout)
    if ok:
        print(f"{args.setting} = {args.value} (verified)")
        return 0
    print(f"{args.setting}: write not confirmed after {args.retries} tries", file=sys.stderr)
    return 1


async def _cmd_send(args: argparse.Namespace) -> int:
    code = args.code if args.code.lower().startswith("0x") else f"0x{args.code}"
    hazard = classify_code(code)
    command = Command(code=code, hazard=hazard, label="raw")
    print(f"{code}: {hazard.value}", flush=True)
    async with _link(args) as link:
        await link.publish(command, allow_motor=args.allow_motor, allow_dangerous=args.allow_dangerous)
    print("sent")
    return 0


async def _cmd_provision(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import ble

    serial = args.serial or input("robot serial (LR4Cxxxxxx): ").strip()
    host = args.host_ip or input("broker IP (e.g. 192.168.1.10): ").strip()
    ca_path = args.ca or input("path to your CA PEM: ").strip()
    ssid = args.wifi_ssid or input("WiFi SSID: ").strip()
    wifi_pass = args.wifi_pass if args.wifi_pass is not None else getpass.getpass(f"WiFi password for {ssid!r}: ")

    ca_pem = Path(ca_path).read_text(encoding="utf-8")
    robots = await ble.scan(timeout=args.scan_timeout, address=args.address)
    if not robots:
        print("no LR4 found advertising — press the robot's Connect button to enter pairing mode", file=sys.stderr)
        return 1
    target = _pick_robot(robots, args.address)

    config = ble.ProvisioningConfig(
        serial=serial, host=host, ca_pem=ca_pem, wifi_ssid=ssid, wifi_pass=wifi_pass,
    )
    mac = await ble.read_device_mac(target.address)
    print(f"\n  RE-PROVISION robot at {target.address} (MAC {mac})\n"
          f"    serial : {serial}\n    broker : {host}\n    wifi   : {ssid}\n"
          f"    reversible via the Whisker app\n")
    if not args.yes and not _confirm("Proceed? Type 'yes': "):
        print("aborted", file=sys.stderr)
        return 1

    result = await ble.provision_robot(target.address, config, dry_run=args.dry_run, on_step=lambda s: print(f"  • {s}"))
    print(result.message)
    return 0 if result.success or args.dry_run else 1


# --- presentation ------------------------------------------------------------
def _print_message(message: StateMessage | ActivityMessage) -> None:
    if isinstance(message, StateMessage):
        _print_state(message)
    else:
        parts = []
        for reading in message.readings:
            name = _REGISTER_NAMES.get(reading.register, "?")
            parts.append(f"0x{reading.register:02X}({name})={reading.value}")
        if parts:
            print("activity: " + "  ".join(parts), flush=True)


def _print_state(message: StateMessage) -> None:
    state = message.state
    fields = {k: v for k, v in asdict(state).items() if k != "raw" and v is not None}
    print("state:", flush=True)
    for key, value in fields.items():
        print(f"  {key} = {value}", flush=True)


# --- value parsing -----------------------------------------------------------
def _build_setting(name: str, raw: str) -> Command:
    match name:
        case "night-light-mode":
            modes = {"off": 0, "on": 1, "auto": 2}
            return commands.set_night_light_mode(modes.get(raw.lower(), _parse_int(raw)))
        case "night-light-brightness":
            return commands.set_night_light_brightness(_parse_int(raw))
        case "clean-cycle-wait":
            return commands.set_clean_cycle_wait_minutes(_parse_int(raw))
        case "keypad-lockout":
            return commands.set_keypad_lockout(_parse_bool(raw))
        case "panel-sleep-mode":
            return commands.set_panel_sleep_mode(_parse_bool(raw))
        case "weekday-sleep-enabled":
            return commands.set_weekday_sleep_enabled(_parse_bool(raw))
        case "panel-sleep-time":
            return commands.set_panel_sleep_time(_parse_time(raw))
        case "panel-wake-time":
            return commands.set_panel_wake_time(_parse_time(raw))
        case "panel-brightness":
            high, _, low = raw.partition(":")
            return commands.set_panel_brightness(_parse_int(high), _parse_int(low or high))
        case _:
            raise SystemExit(f"unknown setting {name!r}")


def _parse_int(value: str) -> int:
    return int(value, 0)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "on", "true", "yes")


def _parse_time(value: str) -> int:
    """'HH:MM' (or a bare minute count) → minutes since midnight."""
    if ":" in value:
        hours, _, minutes = value.partition(":")
        return int(hours) * 60 + int(minutes)
    return int(value)


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() == "yes"
    except EOFError:
        return False


def _pick_robot(robots: Sequence[DiscoveredRobot], address: str | None) -> DiscoveredRobot:
    if len(robots) == 1 or address:
        return robots[0]
    print("multiple robots advertising — pick by RSSI (closest = strongest):")
    for index, robot in enumerate(robots):
        print(f"  [{index}] {robot.address}  RSSI {robot.rssi} dBm  name={robot.name}")
    while True:
        choice = input(f"select [0-{len(robots) - 1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(robots):
            return robots[int(choice)]


# --- argument parsing --------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whiskerless", description="Un-cloud your Whisker devices.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_conn(p: argparse.ArgumentParser, *, serial_required: bool = True) -> None:
        p.add_argument("--host", required=True, help="broker host/IP")
        p.add_argument("--port", type=int, default=8883)
        p.add_argument("--serial", required=serial_required, help="robot serial / MQTT client-id")
        p.add_argument("--ca", help="path to the broker CA PEM")
        p.add_argument("--insecure", action="store_true", help="skip TLS hostname check (CA still verified)")
        p.add_argument("--username")
        p.add_argument("--password")
        p.add_argument("--client-id", default=None, help="MQTT client-id for THIS tool (not the robot)")

    p_monitor = sub.add_parser("monitor", help="watch state + activity (read-only)")
    add_conn(p_monitor)
    p_monitor.add_argument("--duration", type=float, default=60.0)
    p_monitor.set_defaults(func=_cmd_monitor)

    p_state = sub.add_parser("state", help="request and decode the full state document")
    add_conn(p_state)
    p_state.add_argument("--timeout", type=float, default=12.0)
    p_state.set_defaults(func=_cmd_state)

    p_read = sub.add_parser("read", help="type-1 read a register")
    add_conn(p_read)
    p_read.add_argument("register", help="register, e.g. 0x47 or 71")
    p_read.add_argument("--timeout", type=float, default=8.0)
    p_read.set_defaults(func=_cmd_read)

    p_set = sub.add_parser("set", help="change a setting (write + read-back verify)")
    add_conn(p_set)
    p_set.add_argument("setting", choices=[
        "night-light-mode", "night-light-brightness", "clean-cycle-wait",
        "keypad-lockout", "panel-sleep-mode", "weekday-sleep-enabled",
        "panel-sleep-time", "panel-wake-time", "panel-brightness",
    ])
    p_set.add_argument("value", help="e.g. auto | 50 | on | 22:00 | 50:50")
    p_set.add_argument("--retries", type=int, default=3)
    p_set.add_argument("--timeout", type=float, default=8.0)
    p_set.set_defaults(func=_cmd_set)

    p_send = sub.add_parser("send", help="send a raw 0xTTRRVVVV code (guarded by safety)")
    add_conn(p_send)
    p_send.add_argument("code", help="e.g. 0x02A00000")
    p_send.add_argument("--allow-motor", action="store_true")
    p_send.add_argument("--allow-dangerous", action="store_true")
    p_send.set_defaults(func=_cmd_send)

    p_prov = sub.add_parser("provision", help="re-provision a robot onto your broker over BLE")
    p_prov.add_argument("--serial", help="robot serial (prompted if omitted)")
    p_prov.add_argument("--host-ip", help="broker IP to provision (prompted if omitted)")
    p_prov.add_argument("--ca", help="path to your CA PEM (prompted if omitted)")
    p_prov.add_argument("--wifi-ssid", help="WiFi SSID (prompted if omitted)")
    p_prov.add_argument("--wifi-pass", default=None, help="WiFi password (prompted securely if omitted)")
    p_prov.add_argument("--address", help="BLE MAC to target directly (skip the picker)")
    p_prov.add_argument("--scan-timeout", type=float, default=15.0)
    p_prov.add_argument("--dry-run", action="store_true", help="scan/connect and print steps, write nothing")
    p_prov.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_prov.set_defaults(func=_cmd_provision)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")
    try:
        return cast(int, asyncio.run(args.func(args)))
    except KeyboardInterrupt:
        return 130
    except SafetyError as exc:
        print(f"refused by safety guard: {exc}", file=sys.stderr)
        return 2
    except WhiskerlessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
