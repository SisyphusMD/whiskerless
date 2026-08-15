"""whiskerless command-line interface.

A friendly front-end over the library: re-provision a robot onto your broker,
watch its telemetry, read/decode its state, and change settings (with read-back
verify). Every send goes through the safety guard, so the CLI cannot fire a
brick/reset-class command.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import logging
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import aclosing, suppress
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import cast

import aiomqtt

from . import __version__
from .ble.provision import ProvisioningConfig
from .ble.transport import DiscoveredRobot
from .console import Console
from .devices.litter_robot_4 import commands, const, derive
from .devices.litter_robot_4.calibration import (
    LITTER_MAX_SPAN_MM,
    LITTER_MIN_SPAN_MM,
    LITTER_PLAUSIBLE_MM,
    litter_is_sampleable,
)
from .devices.litter_robot_4.commands import Command
from .devices.litter_robot_4.link import LitterRobot4Link
from .devices.litter_robot_4.models import LitterRobot4State, litter_level_percent_from_mm
from .devices.litter_robot_4.protocol import ActivityMessage, StateMessage
from .exceptions import ProfileError, SafetyError, WhiskerlessError
from .profiles import ProfileStore, RobotProfile, Serial, SharedSetup, merge_overrides
from .safety import classify_code

log = logging.getLogger("whiskerless")

# Styling decided once, at import: under a pipe (including every test) this
# resolves to plain text, so nothing downstream needs a color branch.
_console = Console()

_REGISTER_NAMES = {int(r): r.name.lower() for r in const.Register}


# --- connection helpers ------------------------------------------------------
def _read_pem(raw: str) -> str:
    """Read a CA file, expanding ``~`` and failing with something a person can act on.

    ``~`` matters more here than it looks: the path is often typed at a prompt
    inside this program, so the shell never sees it and never expands it.
    """
    path = Path(raw).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WhiskerlessError(
            f"no such file: {path} — check the path, and note that a relative path is "
            "resolved from the directory you ran this in"
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise WhiskerlessError(f"could not read {path}: {exc}") from exc
    if "BEGIN CERTIFICATE" not in text:
        # Checked here, at the prompt, not five answers later: a readable file
        # that is not a PEM would otherwise survive this question and throw away
        # everything typed after it — including a password typed blind.
        raise WhiskerlessError(f"{path} is not a PEM certificate (no BEGIN CERTIFICATE in it)")
    return text


def _profile(args: argparse.Namespace) -> RobotProfile:
    """The robot to act on: whatever was saved, with command-line flags laid over it."""
    store = ProfileStore.from_env()
    try:
        saved = store.resolve(args.serial)
    except ProfileError:
        # Nothing saved for this robot. A fully-explicit invocation still has to
        # work: it is how this behaved before there was a store, and it is what
        # scripts and one-off connections to somebody else's broker rely on.
        if not (args.serial and args.host):
            if args.host and not args.serial:
                raise WhiskerlessError(
                    "--host alone is not enough for a robot not saved here — add "
                    "--serial too (it names the MQTT topics)"
                ) from None
            raise
        saved = RobotProfile(serial=Serial(args.serial), host=args.host)
    return merge_overrides(
        saved,
        host=args.host,
        port=args.port,
        username=args.username,
        # An env var beats --password: a flag lands in shell history and in `ps`.
        password=args.password or os.environ.get("WHISKERLESS_PASSWORD"),
        verify_hostname=None if args.insecure is None else not args.insecure,
        ca_pem=None if args.ca is None else _read_pem(args.ca),
    )


def _link(
    args: argparse.Namespace,
    *,
    subscribe: bool = True,
    profile: RobotProfile | None = None,
) -> LitterRobot4Link:
    if profile is None:
        profile = _profile(args)
    return LitterRobot4Link(
        profile.settings(client_id=args.client_id), profile.serial.value, subscribe=subscribe
    )


# How long to spend clearing documents that arrived before we asked. Long enough
# to empty a queue, short enough that nobody notices; a document that lands
# during the drain simply costs one more request.
_DRAIN_SECONDS = 0.25


# --- command handlers --------------------------------------------------------
async def _cmd_monitor(args: argparse.Namespace) -> int:
    # Resolved before the banner: args.serial is None whenever the robot comes
    # from the store, and "monitoring None" is not a robot anyone owns.
    profile = _profile(args)
    print(
        f"monitoring {profile.display_name} for {args.duration:.0f}s (ctrl-c to stop)…",
        flush=True,
    )
    async with _link(args, profile=profile) as link:
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
    batch = _build_setting(args.setting, args.value)
    failed: Command | None = None
    async with _link(args) as link:
        for command in batch:
            if not await link.apply_setting(command, retries=args.retries, timeout=args.timeout):
                failed = command
                break
    if failed is None:
        print(f"{args.setting} = {args.value} (verified)")
        return 0
    print(f"{args.setting}: write not confirmed after {args.retries} tries", file=sys.stderr)
    if failed.register in _DERIVED_REGISTERS:
        print(_DERIVED_REGISTERS[failed.register], file=sys.stderr)
    return 1


async def _cmd_clean_cycle(args: argparse.Namespace) -> int:
    if not args.yes and not _confirm("Run a clean cycle? The globe will turn. Type 'yes': "):
        print("aborted", file=sys.stderr)
        return 1
    async with _link(args) as link:
        await link.publish(commands.clean_cycle())
    print("clean cycle requested")
    return 0


async def _cmd_empty_cycle(args: argparse.Namespace) -> int:
    if not args.yes:
        _console.banner("EMPTY CYCLE — the globe dumps ALL of its litter")
    if not args.yes and not _confirm(
        "Run an empty cycle? EVERY gram of litter goes into the waste drawer, "
        "and the globe parks until you press Cycle or Reset. Type 'yes': "
    ):
        print("aborted", file=sys.stderr)
        return 1
    async with _link(args) as link:
        await link.publish(commands.empty_cycle())
    print("empty cycle requested")
    return 0


async def _cmd_power(args: argparse.Namespace) -> int:
    # Unlike every other action here, this one can end with the robot off the
    # network — so the prompt is not skippable by --yes and the guard still has
    # to be opted past explicitly.
    _console.banner("POWER TOGGLES — switched off, the robot leaves the network")
    if not _confirm(
        "Press Power? This TOGGLES the robot. If it turns OFF it leaves the "
        "network, and only someone standing at the machine can turn it back on. "
        "Type 'yes': "
    ):
        print("aborted", file=sys.stderr)
        return 1
    async with _link(args) as link:
        await link.publish(commands.power_toggle(), allow_dangerous=True)
    print("power press sent (the robot may now be off)")
    return 0


async def _fresh_state(args: argparse.Namespace, link: LitterRobot4Link) -> LitterRobot4State | None:
    """Ask for a state document and return the first one that lands.

    Every derived view here is built from ONE document, so it has to be a fresh
    one: the alternative is describing the robot as it was whenever the last
    message happened to arrive.
    """
    # Anything already queued describes the robot BEFORE we asked — the LR4
    # pushes state on its own cadence, and `calibrate` is run seconds after
    # someone filled or emptied the globe, so accepting a queued document would
    # pin a permanent reference to the state that person just changed.
    with suppress(TimeoutError):
        async with asyncio.timeout(_DRAIN_SECONDS), aclosing(link.messages()) as queued:
            async for _ in queued:
                pass

    await link.request_state()
    try:
        # aclosing, because returning from inside the loop leaves the generator
        # suspended for the garbage collector to finalise whenever it likes.
        async with asyncio.timeout(args.timeout), aclosing(link.messages()) as stream:
            async for message in stream:
                if isinstance(message, StateMessage):
                    return message.state
    except TimeoutError:
        return None
    return None


def _calibration_problem(full_mm: int | None, empty_mm: int | None) -> str | None:
    """Why this pair cannot be a scale, or None if it can.

    One rule, consulted twice: `calibrate` refuses to WRITE a pair that fails it,
    and `status` refuses to TRUST one — a profile is a file on disk, and a
    hand-edited pair would otherwise be presented as a calibration while quietly
    producing wrong percentages.
    """
    low, high = LITTER_PLAUSIBLE_MM
    for label, value in (("full", full_mm), ("empty", empty_mm)):
        if value is not None and not low <= value <= high:
            return (
                f"{label} reads {value} mm, outside the {low}-{high} mm a litter bed "
                "can physically occupy"
            )
    if full_mm is None or empty_mm is None:
        return None
    span = empty_mm - full_mm
    # Bounded at BOTH ends: an emptier globe is FARTHER away, and the globe holds
    # only a couple of inches of litter, so the gap cannot be large either.
    if not LITTER_MIN_SPAN_MM <= span <= LITTER_MAX_SPAN_MM:
        return (
            f"empty reads {empty_mm} mm and full reads {full_mm} mm. An emptier globe is "
            f"FARTHER away, and the gap should be {LITTER_MIN_SPAN_MM}-{LITTER_MAX_SPAN_MM} mm "
            "— the globe only holds so much litter"
        )
    return None


async def _cmd_status(args: argparse.Namespace) -> int:
    """The derived view — what Home Assistant shows, from one document.

    Deliberately NOT everything HA shows. Cat weight, visit history, the learned
    scales and the last dispense are assembled from a stream over days; a
    one-shot command that printed them would be printing zeros. What a single
    document plus this robot's stored calibration can honestly answer is here,
    and the rest is named as needing a listener rather than silently missing.
    """
    profile = _profile(args)
    async with _link(args, profile=profile) as link:
        robot = await _fresh_state(args, link)
    if robot is None:
        print("no state document received (is the robot online?)", file=sys.stderr)
        return 1

    broken_pair = _calibration_problem(profile.litter_full_mm, profile.litter_empty_mm)
    full_mm, empty_mm = derive.litter_scale(
        derive.DerivedState(),
        # A pair that cannot be a scale is not used as one: the default curve is
        # a worse answer than a good calibration and a far better one than a
        # broken calibration presented as fact.
        full_mm=None if broken_pair else profile.litter_full_mm,
        empty_mm=None if broken_pair else profile.litter_empty_mm,
    )
    percent = (
        robot.litter_level
        if robot.litter_level_reported or robot.litter_level_mm is None
        else litter_level_percent_from_mm(robot.litter_level_mm, full_mm=full_mm, empty_mm=empty_mm)
    )
    if robot.litter_level_reported:
        # The firmware published a percentage of its own, which outranks any
        # reference we hold — calling this robot "uncalibrated" would blame the
        # calibration for a number it had no part in.
        calibration = "not used — this robot reports its own percentage"
    elif broken_pair is not None:
        calibration = f"stored calibration is unusable — {broken_pair}. Re-run `whiskerless calibrate`"
    elif profile.litter_full_mm is None:
        calibration = "not calibrated (using the default curve)"
    else:
        calibration = f"{profile.litter_full_mm} mm when full"
        if profile.litter_empty_mm is not None:
            calibration += f", {profile.litter_empty_mm} mm when empty"

    # The robot keeps reporting a level while a cat is standing in the globe, and
    # the ToF is then measuring the cat: a captured visit read 253 mm against a
    # 428-462 mm bed. Home Assistant rides this out because it updates again in a
    # minute; a one-shot is whatever moment you happened to ask in, so it says so.
    level = "unknown" if percent is None else f"{percent}%"
    if robot.litter_level_mm is not None and not litter_is_sampleable(robot):
        # Only when there IS a reading and it cannot be trusted. A document that
        # simply carries no distance is missing telemetry, not a robot with a
        # cat in it, and saying "not settled" about a settled robot is worse
        # than saying nothing.
        level += " (not a clean reading — the robot is not settled and empty)"

    rows: list[tuple[str, object]] = [
        ("status", robot.robot_status),
        ("litter level", level),
        ("litter distance", "unknown" if robot.litter_level_mm is None else f"{robot.litter_level_mm} mm"),
        ("calibration", calibration),
        ("waste drawer", "unknown" if robot.waste_drawer_level is None else f"{robot.waste_drawer_level}%"),
        ("drawer full", robot.is_dfi_full),
        ("cat present", robot.cat_detected),
        ("weight on the scale", robot.scale_loaded),
        ("bonnet removed", robot.is_bonnet_removed),
        # A ZERO here is not evidence of no fault: one robot held a live
        # globe-motor fault for 50 minutes while this field read 0 in every
        # state document it published. A non-zero field is still a fault, so
        # say that and stay silent otherwise — the honest verdict needs the
        # activity stream, which a one-shot does not have.
        ("globe motor fault", robot.globe_motor_fault or None),
        ("panel sleeping", robot.panel_sleep_mode),
        ("control lock", robot.keypad_lockout),
        ("clean cycle wait", None if robot.clean_cycle_wait_minutes is None else f"{robot.clean_cycle_wait_minutes} min"),
        ("clean cycles", robot.odometer_clean_cycles),
        ("firmware (ESP)", robot.esp_firmware),
        ("Wi-Fi signal", None if robot.wifi_rssi is None else f"{robot.wifi_rssi} dBm"),
    ]
    print(_console.accent(profile.display_name))
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        if value is None:
            continue
        print(f"  {_console.dim(label.ljust(width))}  {value}")
    print()
    print(
        _console.dim(
            "Cat weight, visits, motor faults and the learned scales need a listener\n"
            "running over time — Home Assistant has them. A one-shot sees one document."
        )
    )
    return 0


async def _cmd_calibrate(args: argparse.Namespace) -> int:
    """Record what a person can see and the robot cannot: what full looks like.

    Stored per robot on this machine, beside the broker details. The reading is
    taken from a FRESH document because the globe was just filled or emptied —
    the last one to arrive describes the robot before that happened.
    """
    profile = _profile(args)
    empty = args.point == "empty"
    async with _link(args, profile=profile) as link:
        robot = await _fresh_state(args, link)
    if robot is None:
        print("no state document received (is the robot online?)", file=sys.stderr)
        return 1
    if robot.litter_level_mm is None or not litter_is_sampleable(robot):
        print(
            "the robot is not reporting a usable litter distance right now — it "
            f"reads {robot.robot_status}; try again once it is idle and empty",
            file=sys.stderr,
        )
        return 1
    low, high = LITTER_PLAUSIBLE_MM
    if not low <= robot.litter_level_mm <= high:
        # The settled-and-empty check above is about the robot's STATUS; this is
        # about physics. A cat's back measured 253 mm in one capture, and a
        # reference is permanent — every later percentage is read against it.
        print(
            f"{robot.litter_level_mm} mm is outside the range a litter bed can occupy "
            f"({low}-{high} mm) — something is in the globe, or the sensor is confused",
            file=sys.stderr,
        )
        return 1
    # Saved against what is ON DISK, not against the profile we connected with:
    # `--host` for a one-off connection must not rewrite the stored broker, and
    # the merged profile carries this run's password in memory.
    store = ProfileStore.from_env()
    try:
        stored = store.resolve(args.serial)
    except ProfileError:
        print(
            "this robot is not saved on this machine, so there is nowhere to keep "
            "a calibration — run `whiskerless provision` first",
            file=sys.stderr,
        )
        return 1
    # A stored pair that is already unusable must not veto its own repair: the
    # new reading would be judged against the bad endpoint, fail, and leave the
    # user following `status`'s advice to re-run this command forever. Starting
    # over means starting over — the other point goes.
    starting_over = _calibration_problem(stored.litter_full_mm, stored.litter_empty_mm) is not None
    kept_full = None if starting_over else stored.litter_full_mm
    kept_empty = None if starting_over else stored.litter_empty_mm
    updated = replace(
        stored,
        litter_empty_mm=robot.litter_level_mm if empty else kept_empty,
        litter_full_mm=kept_full if empty else robot.litter_level_mm,
    )
    # More litter means a SHORTER distance, so empty must read farther than full.
    # Recorded the other way round — the two commands swapped, or the globe not
    # actually emptied — the pair is an impossible scale that the percentage
    # silently ignores while `status` goes on calling the robot calibrated.
    problem = _calibration_problem(updated.litter_full_mm, updated.litter_empty_mm)
    if problem is not None:
        print(f"that pair cannot be right: {problem}. Nothing saved.", file=sys.stderr)
        return 1
    store.save(updated)
    point = "empty" if empty else "full"
    print(f"{point} reference for {profile.display_name}: {robot.litter_level_mm} mm")
    if starting_over:
        print("(the calibration stored before this could not be a scale, so it was cleared)")
    return 0


async def _cmd_panel_reset(args: argparse.Namespace) -> int:
    """Press Reset: acknowledge a full-drawer alarm, or release a stalled cycle."""
    async with _link(args) as link:
        await link.publish(commands.panel_reset())
    print("reset press sent")
    return 0


async def _cmd_send(args: argparse.Namespace) -> int:
    code = args.code if args.code.lower().startswith("0x") else f"0x{args.code}"
    hazard = classify_code(code)
    command = Command(
        code=code, hazard=hazard, label="raw",
        at_most_once=commands.is_edge_triggered(code),
    )
    print(f"{code}: {hazard.value}", flush=True)
    async with _link(args) as link:
        await link.publish(command, allow_dangerous=args.allow_dangerous)
    print("sent")
    return 0


async def _cmd_provision(args: argparse.Namespace) -> int:
    from . import ble

    # Another robot almost always lands on the same broker, behind the same CA,
    # on the same WiFi as the ones already here — so offer that rather than making
    # someone find the CA path again.
    prior, shared = _prior_setup()
    if prior is not None:
        print("  press enter at any prompt to accept the setup already in use here\n")

    # Each answer is checked as it is given. Validating later means a typo in the
    # third question throws away all five — including a password typed blind.
    # The label prints TWO strings that both start with LR4; the hyphenated one
    # (LR4-0301-00-US) is the model, and picking it provisions a robot that then
    # never appears on the broker.
    serial = _ask(
        "robot serial (the unhyphenated LR4C… line on the label, e.g. LR4C123456 — "
        "NOT the LR4-…-US model number): ",
        args.serial,
        ble.ProvisioningConfig.check_serial,
    )
    # Host and SSID show their own value, so they are unambiguous however many
    # robots are saved. A CA is a blob of PEM that cannot go in a prompt, so it
    # needs describing — and only when the robots disagree is naming one of them
    # meaningful rather than arbitrary.
    host = _ask(
        "broker IP (e.g. 192.168.1.10): ", args.host_ip, _check_host,
        default=shared.host or (prior.host if prior else None),
    )
    ca_default = shared.ca_pem or (prior.ca_pem if prior else None)
    ca_pem = _ask(
        "path to your CA PEM: ", args.ca, _read_pem,
        default=ca_default,
        default_label=_ca_label(shared, prior) if ca_default else None,
    )
    # Optional, and the only broker field that is: an authenticated broker
    # otherwise provisions cleanly and then fails every later bare command until
    # someone passes --username by hand or edits profile.json. The password is
    # deliberately NOT asked for — it is never written down (see profiles.py).
    # This robot's OWN recorded login, if it has one: a reprovision must not lose
    # it, and it is the only value safe to adopt without anyone looking.
    own_username: str | None = None
    with contextlib.suppress(ProfileError):
        own_username = ProfileStore.from_env().load(serial).username
    username = _ask_optional(
        "broker username",
        args.username,
        own_username if own_username is not None else shared.username,
        unattended=own_username,
    )
    ssid = _ask(
        "WiFi SSID: ", args.wifi_ssid, _check_ssid,
        default=shared.wifi_ssid or (prior.wifi_ssid or None if prior else None),
    )
    # The WiFi passphrase is deliberately never stored, so it is always asked for.
    wifi_pass = args.wifi_pass if args.wifi_pass is not None else getpass.getpass(f"WiFi password for {ssid!r}: ")

    # Not part of ProvisioningConfig: the robot authenticates to the broker with
    # its own factory certificate, so this login is whiskerless's, not the
    # robot's, and nothing about it is written over BLE.
    config = ble.ProvisioningConfig(
        serial=serial, host=host, ca_pem=ca_pem, wifi_ssid=ssid, wifi_pass=wifi_pass,
    )

    # The scan is the one stretch a first-time user stares at with nothing
    # moving — indistinguishable from hung without a liveness row.
    with _console.progress("scanning for robots over BLE"):
        robots = await ble.scan(timeout=args.scan_timeout, address=args.address)
    if not robots:
        # HOLD, not press: a short press does nothing, which reads as "the tool
        # is broken" — that exact misunderstanding happened live.
        print(
            "no LR4 found advertising — HOLD the robot's Connect button a few seconds, "
            "until its light pulses yellow (that is pairing mode), then rerun",
            file=sys.stderr,
        )
        return 1
    target = _pick_robot(robots, args.address)

    mac = await ble.read_device_mac(target.address)
    print(f"\n  RE-PROVISION robot at {target.address} (MAC {mac})\n"
          f"    serial : {config.serial}\n    broker : {host}\n    wifi   : {ssid}\n"
          f"    reversible via the Whisker app\n")
    if args.dry_run:
        print("  DRY RUN — the BLE connect, endpoint discovery and reads below are real;\n"
              "  nothing is written to the robot.\n")
    if not args.yes and not _confirm("Proceed? Type 'yes': "):
        print("aborted", file=sys.stderr)
        return 1

    result = await ble.provision_robot(target.address, config, dry_run=args.dry_run, on_step=lambda s: print(f"  • {s}"))
    print(result.message)
    if args.dry_run:
        return 0
    if not result.success:
        return 1

    # Written only after the robot accepted it, so a failed run never leaves a
    # profile claiming a robot is reachable somewhere it is not.
    _save_profile(config, args, username)
    return 0


def _prior_setup() -> tuple[RobotProfile | None, SharedSetup]:
    """What a newly provisioned robot can inherit from the ones already here.

    Returns both what every robot agrees on and one robot to fall back on for
    the fields where they disagree.
    """
    store = ProfileStore.from_env()
    known = store.list_profiles()
    if not known:
        return None, SharedSetup()
    default = store.get_default()
    fallback = next((p for p in known if p.serial.value == default), known[0])
    return fallback, SharedSetup.from_profiles(known)


def _ca_label(shared: SharedSetup, prior: RobotProfile | None) -> str:
    if shared.ca_pem is not None:
        return "the CA already in use here"
    return f"the CA saved for {prior.display_name}" if prior else "the saved CA"


def _save_profile(
    config: ProvisioningConfig, args: argparse.Namespace, username: str | None
) -> None:
    store = ProfileStore.from_env()
    try:
        prior = store.load(config.serial)
    except ProfileError:
        prior = None
    if prior is None:
        profile = RobotProfile(
            serial=Serial(config.serial),
            host=config.host,
            name=args.name or "",
            username=username,
            ca_pem=config.ca_pem,
            wifi_ssid=config.wifi_ssid,
        )
    else:
        # Reprovisioning replaces only what provisioning collected. The name,
        # broker credentials and port were never asked for, so writing defaults
        # over them would silently erase what the user set up.
        profile = replace(
            prior,
            serial=Serial(config.serial),
            host=config.host,
            name=args.name or prior.name,
            username=username,
            ca_pem=config.ca_pem,
            wifi_ssid=config.wifi_ssid,
            password=None,
        )
    try:
        store.save(profile)
        if store.get_default() is None:
            store.set_default(profile.serial.value)
    except OSError as exc:
        # The robot is already provisioned; failing to write a convenience file
        # must not report that as a failed provisioning.
        print(f"note: could not save the profile ({exc.strerror or exc}) — "
              f"later commands will need --host", file=sys.stderr)
        return
    print(f"\n  saved as {profile.display_name} — later commands need no flags:\n"
          f"    whiskerless state\n")


# --- saved robots -------------------------------------------------------------
async def _cmd_robots(args: argparse.Namespace) -> int:
    store = ProfileStore.from_env()
    known = store.list_profiles()
    broken = store.damaged()
    if not known and not broken:
        print("no robots are set up on this machine — run `whiskerless provision`")
        return 0
    default = store.get_default()
    for profile in known:
        marker = "*" if profile.serial.value == default else " "
        confirmed = "" if profile.serial.verified else "  (serial as typed, unconfirmed)"
        print(f" {marker} {profile.display_name:<20} {profile.host}:{profile.port}{confirmed}")
    for name, why in broken:
        print(f" ! {name:<20} unreadable — {why}")
    if broken:
        print("\n  ! damaged — re-run `whiskerless provision`, or drop it with `whiskerless forget`")
    if default:
        print("\n  * default — override per command with --serial")
    return 0


async def _cmd_use(args: argparse.Namespace) -> int:
    store = ProfileStore.from_env()
    # Resolved before it becomes the default: pointing every future bare
    # command at a profile that cannot load helps nobody.
    profile = store.resolve(args.robot)
    store.set_default(profile.serial.value)
    print(f"{profile.display_name} is now the default")
    return 0


async def _cmd_forget(args: argparse.Namespace) -> int:
    store = ProfileStore.from_env()
    try:
        name = store.resolve(args.robot).display_name
    except ProfileError:
        # A profile too corrupt to load is precisely the one `forget` must
        # still be able to remove.
        name = Serial(args.robot).value
        if not (store.robots_dir / name).is_dir():
            raise
    if not args.yes and not _confirm(
        f"Forget {name}? This only removes the saved broker "
        "details from this machine; the robot keeps running. Type 'yes': "
    ):
        print("aborted", file=sys.stderr)
        return 1
    store.forget(args.robot)
    print(f"forgot {name}")
    return 0


def _print_orientation() -> None:
    """What a bare `whiskerless` says — which depends on whether anything is set up."""
    known = ProfileStore.from_env().list_profiles()
    print("\n  whiskerless — local MQTT control for the Litter-Robot 4. No cloud.\n")
    if not known:
        print("  Nothing is set up on this machine yet.\n\n"
              "    whiskerless provision      point a robot at your broker (over BLE, once)\n")
    else:
        names = ", ".join(profile.display_name for profile in known)
        print(f"  Set up here: {names}\n\n"
              "    whiskerless state          ask a robot for its full status\n"
              "    whiskerless monitor        watch its telemetry live\n"
              "    whiskerless robots         list what this machine knows\n")
    print("  All commands   whiskerless --help\n"
          "  Docs           https://github.com/SisyphusMD/whiskerless\n")


# --- presentation ------------------------------------------------------------
def _print_message(message: StateMessage | ActivityMessage) -> None:
    if isinstance(message, StateMessage):
        _print_state(message)
    else:
        parts = []
        for reading in message.readings:
            name = _REGISTER_NAMES.get(reading.register, "?")
            # Raw code first: tying a physical action to its exact bytes is the
            # whole point of a capture session, and the decoded form loses it.
            parts.append(f"{reading.hex} {_console.accent(name)}={reading.value}")
        if parts:
            stamp = datetime.now().astimezone().strftime("%H:%M:%S")
            print(f"{_console.dim(stamp)} activity: " + "  ".join(parts), flush=True)


def _print_state(message: StateMessage) -> None:
    state = message.state
    fields = {k: v for k, v in asdict(state).items() if k != "raw" and v is not None}
    print("state:", flush=True)
    for key, value in fields.items():
        print(f"  {_console.dim(key)} = {value}", flush=True)


# --- value parsing -----------------------------------------------------------
# The firmware computes this one rather than storing it, so a write is accepted and
# discarded; the only useful thing to say is where the real setting lives.
_DERIVED_REGISTERS: dict[int, str] = {
    const.Register.IS_PANEL_SLEEP_MODE: (
        "hint: 0x1A follows the weekday sleep schedule — set weekday-sleep-enabled instead"
    ),
}


def _build_setting(name: str, raw: str) -> tuple[Command, ...]:
    match name:
        case "night-light-mode":
            modes = {"off": 0, "on": 1, "auto": 2}
            # Looked up before falling back, not as get()'s default: a default
            # argument is evaluated eagerly, so _parse_int would raise on the
            # very spellings this map exists to accept.
            named = modes.get(raw.lower())
            return (commands.set_night_light_mode(_parse_int(raw) if named is None else named),)
        case "night-light-brightness":
            return (commands.set_night_light_brightness(_parse_int(raw)),)
        case "clean-cycle-wait":
            return (commands.set_clean_cycle_wait_minutes(_parse_int(raw)),)
        case "keypad-lockout":
            return (commands.set_keypad_lockout(_parse_bool(raw)),)
        case "panel-sleep-mode":
            return (commands.set_panel_sleep_mode(_parse_bool(raw)),)
        case "weekday-sleep-enabled":
            return (commands.set_weekday_sleep_enabled(_parse_bool(raw)),)
        case "panel-sleep-time":
            return commands.set_panel_sleep_times(_parse_time(raw))
        case "panel-wake-time":
            return commands.set_panel_wake_times(_parse_time(raw))
        case "panel-brightness":
            high, _, low = raw.partition(":")
            return (commands.set_panel_brightness(_parse_int(high), _parse_int(low or high)),)
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


def _ask_optional(
    prompt: str, supplied: str | None, default: str | None, *, unattended: str | None = None
) -> str | None:
    """Ask something the robot may legitimately not have.

    Distinct from :func:`_ask`, where an empty answer means "use the default":
    here it can also mean "there is no such thing", and the two have to be
    expressible separately or an anonymous broker could never be described once
    a previous robot had recorded a login.

    ``unattended`` is what to use when there is nobody to ask, and it is
    deliberately allowed to be narrower than ``default``. A value offered from
    OTHER robots is a suggestion someone reads and accepts; taking that same
    suggestion silently, in a script, would write another broker's login into
    this robot's profile and leave it failing to connect with no sign why.
    """
    if supplied is not None:
        return supplied or None
    if not sys.stdin.isatty():
        # A scripted run supplies what it wants on the command line, and an
        # OPTIONAL question must never be the thing that makes an otherwise
        # fully-flagged invocation hang or fail. The required questions still
        # prompt (and still fail loudly on EOF) because there is no sane
        # substitute for a missing serial.
        return unattended
    hint = f" [{default}, or '-' for none]" if default else " (enter to skip)"
    try:
        answer = input(f"{prompt.rstrip(': ')}{hint}: ").strip()
    except EOFError:
        raise WhiskerlessError("no answer given (input ended)") from None
    if not answer:
        return default
    return None if answer == "-" else answer


def _ask(
    prompt: str,
    supplied: str | None,
    check: Callable[[str], str],
    *,
    default: str | None = None,
    default_label: str | None = None,
) -> str:
    """Return a validated answer, re-asking until it passes.

    A value from the command line is checked once and its failure is fatal —
    there is nobody at a prompt to correct it. A typed answer is re-asked, which
    is the whole point of validating at the prompt instead of five steps later.

    ``default`` is returned unchecked when the user just presses enter; it comes
    from a robot already set up here, so it has been validated once already and
    may not even be in the same form as typed input (the CA is contents, not a
    path). ``default_label`` is what to show when the value itself would not be
    readable in a prompt.
    """
    if supplied is not None:
        return check(supplied)
    if default is not None:
        prompt = f"{prompt.rstrip(': ')} [{default_label or default}]: "
    while True:
        try:
            answer = input(prompt).strip()
        except EOFError:
            raise WhiskerlessError("no answer given (input ended)") from None
        if not answer and default is not None:
            return default
        try:
            return check(answer)
        except WhiskerlessError as exc:
            print(f"  {exc}", file=sys.stderr)


def _check_host(value: str) -> str:
    if not value:
        raise WhiskerlessError("a broker host or IP is required")
    if "/" in value or " " in value:
        raise WhiskerlessError(f"{value!r} is not a host or IP — give just the address, e.g. 192.168.1.10")
    return value


def _check_ssid(value: str) -> str:
    if not value:
        raise WhiskerlessError("a WiFi SSID is required")
    return value


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
    parser.add_argument("--version", action="version", version=f"whiskerless {__version__}")
    parser.add_argument("--debug", action="store_true",
                        help="show the full traceback on failure (for bug reports)")

    # People type `whiskerless state --debug`, not `whiskerless --debug state`, so
    # these have to work in both positions. SUPPRESS is load-bearing: a subparser
    # copies its parent's actions and writes their DEFAULTS over the namespace the
    # top-level parser already filled, so a plain default here would silently
    # discard a --debug given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="show the full traceback on failure (for bug reports)")
    common.add_argument("-v", "--verbose", action="count", default=argparse.SUPPRESS,
                        help="-v info, -vv debug")

    # Not required: a bare invocation prints an orientation instead of an
    # argparse usage error, which is the one thing a first-time user cannot use.
    sub = parser.add_subparsers(dest="command", parser_class=argparse.ArgumentParser)

    def add_parser(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    def add_conn(p: argparse.ArgumentParser) -> None:
        # Everything here defaults to None so "not given" stays distinguishable
        # from "given the same value the saved profile holds" — otherwise every
        # flag would silently override the stored profile with argparse defaults.
        p.add_argument("--serial", help="which robot (default: the only one saved, or `use`)")
        p.add_argument("--host", help="broker host/IP (overrides the saved profile)")
        p.add_argument("--port", type=int, default=None)
        p.add_argument("--ca", help="path to the broker CA PEM (overrides the saved profile)")
        p.add_argument("--insecure", action="store_true", default=None,
                       help="skip TLS hostname check (CA still verified)")
        p.add_argument("--username", default=None)
        p.add_argument("--password", default=None)
        p.add_argument("--client-id", default=None, help="MQTT client-id for THIS tool (not the robot)")

    p_status = add_parser("status", "the derived view: what this robot is doing, in plain terms")
    p_status.add_argument("--timeout", type=float, default=10.0, help="seconds to wait")
    add_conn(p_status)
    p_status.set_defaults(func=_cmd_status)

    p_calibrate = add_parser("calibrate", "record what full (or empty) looks like on this robot")
    p_calibrate.add_argument(
        "point",
        choices=("full", "empty"),
        help="'full' with the globe filled the way you call full, 'empty' with it emptied",
    )
    p_calibrate.add_argument("--timeout", type=float, default=10.0, help="seconds to wait")
    add_conn(p_calibrate)
    p_calibrate.set_defaults(func=_cmd_calibrate)

    p_reset = add_parser("panel-reset", "press Reset (acknowledge an alarm, release a cycle)")
    add_conn(p_reset)
    p_reset.set_defaults(func=_cmd_panel_reset)

    p_monitor = add_parser("monitor", "watch state + activity (read-only)")
    add_conn(p_monitor)
    p_monitor.add_argument("--duration", type=float, default=60.0)
    p_monitor.set_defaults(func=_cmd_monitor)

    p_state = add_parser("state", "request and decode the full state document")
    add_conn(p_state)
    p_state.add_argument("--timeout", type=float, default=12.0)
    p_state.set_defaults(func=_cmd_state)

    p_read = add_parser("read", "type-1 read a register")
    add_conn(p_read)
    p_read.add_argument("register", help="register, e.g. 0x47 or 71")
    p_read.add_argument("--timeout", type=float, default=8.0)
    p_read.set_defaults(func=_cmd_read)

    p_set = add_parser("set", "change a setting (write + read-back verify)")
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

    p_send = add_parser("send", "send a raw 0xTTRRVVVV code (guarded by safety)")
    add_conn(p_send)
    p_send.add_argument("code", help="e.g. 0x02A00000")
    p_send.add_argument("--allow-dangerous", action="store_true")
    p_send.set_defaults(func=_cmd_send)

    p_cycle = add_parser("clean-cycle", "run a clean cycle (turns the globe)")
    add_conn(p_cycle)
    p_cycle.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_cycle.set_defaults(func=_cmd_clean_cycle)

    p_empty = add_parser("empty-cycle", "empty the globe into the waste drawer")
    add_conn(p_empty)
    p_empty.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_empty.set_defaults(func=_cmd_empty_cycle)

    p_power = add_parser("power", "toggle robot power (it may not come back)")
    add_conn(p_power)
    p_power.set_defaults(func=_cmd_power)

    p_prov = add_parser("provision", "re-provision a robot onto your broker over BLE")
    p_prov.add_argument(
        "--serial",
        help="robot serial: the unhyphenated LR4C… label line, not the LR4-…-US model "
        "(prompted if omitted)",
    )
    p_prov.add_argument("--host-ip", help="broker IP to provision (prompted if omitted)")
    p_prov.add_argument("--ca", help="path to your CA PEM (prompted if omitted)")
    p_prov.add_argument("--wifi-ssid", help="WiFi SSID (prompted if omitted)")
    p_prov.add_argument("--wifi-pass", default=None, help="WiFi password (prompted securely if omitted)")
    p_prov.add_argument("--address", help="BLE MAC to target directly (skip the picker)")
    p_prov.add_argument("--scan-timeout", type=float, default=15.0)
    p_prov.add_argument("--dry-run", action="store_true", help="scan/connect and print steps, write nothing")
    p_prov.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_prov.add_argument("--username", help="broker username, if yours needs one (prompted if omitted)")
    p_prov.add_argument("--name", help="what to call this robot afterwards, e.g. 'Upstairs'")
    p_prov.set_defaults(func=_cmd_provision)

    p_robots = add_parser("robots", "list the robots set up on this machine")
    p_robots.set_defaults(func=_cmd_robots)

    p_use = add_parser("use", "choose which robot commands act on by default")
    p_use.add_argument("robot", help="serial of a robot from `whiskerless robots`")
    p_use.set_defaults(func=_cmd_use)

    p_forget = add_parser("forget", "remove a robot's saved details from this machine")
    p_forget.add_argument("robot", help="serial of a robot from `whiskerless robots`")
    p_forget.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_forget.set_defaults(func=_cmd_forget)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")
    debug = args.debug or bool(os.environ.get("WHISKERLESS_DEBUG"))
    if args.command is None:
        _print_orientation()
        return 0
    try:
        return cast(int, asyncio.run(args.func(args)))
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except SafetyError as exc:
        print(f"refused by safety guard: {exc}", file=sys.stderr)
        return 2
    # Everything below prints one line and exits. A user-facing tool must not
    # answer a mistyped path with a stack trace and PyInstaller's "Failed to
    # execute script" — but a bug report needs one, hence --debug.
    except WhiskerlessError as exc:
        if debug:
            raise
        print(f"whiskerless: {exc}", file=sys.stderr)
        return 1
    # The link wraps CONNECT failures, but a broker that drops mid-session
    # surfaces from messages()/publish() as a raw MqttError — still one line.
    except aiomqtt.MqttError as exc:
        if debug:
            raise
        print(f"whiskerless: lost the broker connection ({exc})", file=sys.stderr)
        return 1
    except OSError as exc:
        if debug:
            raise
        print(f"whiskerless: {exc.strerror or exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
