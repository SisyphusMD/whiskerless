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
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from contextlib import aclosing, suppress
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import aiomqtt

from . import __version__, backup, pki, profiles
from .ble.messages import WifiNetwork as DiscoveredNetwork
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
from .mqtt import DEFAULT_TLS_PORT
from .pki import KeyPair
from .profiles import (
    LAYOUT_VERSION,
    AuthMode,
    Broker,
    ProfileStore,
    RobotProfile,
    Serial,
)

if TYPE_CHECKING:  # cryptography is imported lazily; this is for annotations only
    from cryptography import x509
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
    """Which robot to act on. Everything else about the connection is the store's.

    There is one broker per store now, so there is nothing to lay flags over: a
    robot is a serial, a name, and what somebody measured at the machine.
    """
    store = ProfileStore.from_env()
    try:
        return store.resolve(args.serial)
    except ProfileError:
        # A fully explicit invocation still has to work: it is how this behaved
        # before there was a store, and it is what one-off connections rely on.
        if args.serial:
            return RobotProfile(serial=Serial(args.serial))
        raise


def _link(
    args: argparse.Namespace,
    *,
    subscribe: bool = True,
    profile: RobotProfile | None = None,
) -> LitterRobot4Link:
    # No per-command broker overrides. Everything needed is in the store, and a
    # flag pointing at a different broker would still present this store's CA and
    # client certificate — so it could only fail, confusingly. A genuinely
    # different broker is a different store: point WHISKERLESS_HOME at it.
    store = ProfileStore.from_env()
    if profile is None:
        profile = _profile(args)
    return LitterRobot4Link(
        store.settings(client_id=args.client_id), profile.serial.value, subscribe=subscribe
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


async def _cmd_wifi_toggle(args: argparse.Namespace) -> int:
    # Same shape as `power`, and for the same reason: this can end with the robot
    # off the network. --yes does not skip the prompt, and the guard still has to
    # be opted past explicitly.
    _console.banner("CONNECT TOGGLES WIFI — switched off, the robot leaves the network")
    if not _confirm(
        "Press Connect? This TOGGLES the robot's WiFi. If it turns OFF the robot "
        "vanishes from your broker and from Home Assistant, and only someone "
        "standing at the machine can press Connect again. Type 'yes': "
    ):
        print("aborted", file=sys.stderr)
        return 1
    async with _link(args) as link:
        await link.publish(commands.wifi_toggle(), allow_dangerous=True)
    # Deliberately not "sent and confirmed": if the WiFi went off, the robot was
    # gone before it could acknowledge anything, and saying otherwise would claim
    # a fact the transport cannot carry.
    print("connect press sent (if the WiFi is now off, the robot has left the network)")
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


def _drawer_level(robot: LitterRobot4State) -> str:
    """The waste-drawer percentage, said as firmly as the robot actually says it.

    A Reset press zeroes the gauge and raises ``isDFIResetPending`` in the same
    instant; the lasers only measure on the next cycle, which is when the flag
    clears. Between the two the robot is reporting a number it has not taken, and
    it says so — so printing a bare percentage there turns the robot's own
    disclaimer into a reading. Live 2026-08-19 that window was five minutes long
    and the provisional figure was 0 %.
    """
    if robot.waste_drawer_level is None:
        return "unknown"
    level = f"{robot.waste_drawer_level}%"
    if robot.is_dfi_reset_pending:
        return f"{level} (not measured yet — reset, awaiting the next cycle)"
    return level


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
        # The robot says outright when this number has not been measured yet — a
        # Reset zeroes the gauge and flags it until the next cycle's lasers confirm
        # it — and printing the bare percentage anyway presents a guess as a
        # reading. The qualifier is on the value rather than a row of its own so it
        # cannot be read past.
        ("waste drawer", _drawer_level(robot)),
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


async def _cmd_setup(args: argparse.Namespace) -> int:
    """Prepare this machine: the broker it talks to, and the certificates for it.

    Separate from `provision` on purpose. Between generating certificates and a
    robot being able to use them, somebody has to install three files on their
    broker and restart it — and on anything more involved than a local Mosquitto
    that is minutes, not seconds. A robot sits in pairing mode with a limited
    window, so doing this in the middle of a provisioning session would spend the
    window on paperwork and then fail in a way that looks like a broken robot.
    """
    store = ProfileStore.from_env()
    saved = store.load_broker() if store.has_broker() else None
    if args.host:
        host = _check_host(args.host)
    elif saved is not None:
        # Re-running to change a port must not insist on restating the host, and
        # must not hang a scripted run on a prompt it cannot answer.
        host = (
            _ask("broker IP (e.g. 192.168.1.10): ", None, _check_host, default=saved.host)
            if sys.stdin.isatty()
            else saved.host
        )
    else:
        host = _ask("broker IP (e.g. 192.168.1.10): ", None, _check_host)
    # Kept from the store unless this run says otherwise: the mode is a decision,
    # not a per-invocation flag, and a `setup --host` run to move the broker must
    # not quietly move a store off the arrangement it was configured with.
    mode = _resolve_auth_mode(args, saved)
    broker = Broker(host=host, auth=mode)
    # Raises rather than returning a store that cannot produce identities: since
    # 0.2.0 that is an unfinished setup, not an arrangement.
    # Read now, filed later. Overwriting the identity on file before knowing the
    # replacement is usable destroys a working one — and in `supplied` mode the
    # store may hold the only copy of it.
    brought_client = _read_client_pair(args)
    _ensure_pki(args, store, host, mode, brought_client)
    if brought_client is not None:
        # After `_ensure_pki`, because checking the chain needs the CA it files —
        # and before anything reports success, because a certificate the broker
        # will refuse is not an identity.
        _check_supplied_identity(store, brought_client, for_robot=False)
        store.save_client(brought_client)
        print(f"  client identity copied to {store.root / 'client'}")
    # Usable, not merely present: a certificate we just warned about — a foreign
    # CA — must not then be recommended.
    # Printing "install the files above" under a warning that they cannot work is
    # how somebody restarts their broker into a listener no robot can verify.
    serving = (
        _refresh_server_cert(store, host)
        if mode is AuthMode.MUTUAL
        else _report_foreign_server_cert(store, host, mode)
    )
    store.save_broker(broker)
    store.assert_usable(broker)
    # Shown whenever they exist, not only when this run created them. Re-running
    # setup to change a port is a perfectly good moment to be reminded where the
    # broker's files are, and it keeps "the files above" honest either way.
    made_files = serving and (store.broker_dir / "server.crt").is_file()
    if made_files:
        _report_files(store)

    print(f"\n  This machine is set up for the broker at "
          f"{_console.accent(f'{host}:{DEFAULT_TLS_PORT}')}.\n")
    # Only point at files that were actually produced. Importing a CA generates
    # nothing to install, and telling somebody to install "the files above" when
    # nothing was printed above sends them looking for something that is not there.
    if made_files:
        print("  Next: install the files above on your broker and restart it, then\n"
              f"  {_console.accent('whiskerless provision')} with a robot in pairing mode.\n")
    elif mode is not AuthMode.MUTUAL:
        # Nothing is wrong here: this store does not issue the broker's
        # certificate, and said so above. Telling somebody to "fix" a certificate
        # they are about to install themselves reads as a failure and is not one.
        print("  Next: install your broker's certificate and restart it, then\n"
              f"  {_console.accent('whiskerless provision')} with a robot in pairing mode.\n")
    else:
        # A certificate is there and not ours to replace.
        print("  Fix the broker certificate above first — a robot provisioned now would\n"
              "  fail every handshake against it.\n")
    return 0


async def _cmd_diagnose(args: argparse.Namespace) -> int:
    """Ask the robot why its WiFi will not hold. Reads only.

    Exists because the panel says "blinking blue" and nothing else, while the robot
    itself knows whether it was refused, could not see the network, or joined and
    never got a lease. BLE does not need the WiFi up, so this works exactly when
    nothing else does.
    """
    from . import ble

    _console.banner("THIS PUTS THE ROBOT IN PAIRING MODE — WHICH TAKES IT OFF WIFI")
    print(
        "  Reading the robot's status needs it advertising over Bluetooth, and the\n"
        "  only way in is pairing mode — which makes it forget its saved network.\n"
        "  It will NOT rejoin on its own afterwards: finish with a `provision`.\n\n"
        "  So run this when the robot is ALREADY failing and you are prepared to\n"
        "  re-provision it. It is not a free look.\n"
    )
    if not (args.yes or _confirm("Continue? Type 'yes': ")):
        print("aborted", file=sys.stderr)
        return 1

    print(
        f"\n  Hold {_console.accent('Connect')} until the light "
        f"{_console.accent('BLINKS YELLOW')}, and keep holding\n"
        "  until the numbered lines below start.\n"
    )
    with _console.progress("scanning for robots over BLE"):
        robots = await ble.scan(timeout=args.scan_timeout, address=args.address)
    if not robots:
        print(
            "no LR4 found advertising — HOLD Connect for about three seconds, until "
            "the light BLINKS YELLOW, then rerun.",
            file=sys.stderr,
        )
        return 1
    target = _pick_robot(robots, args.address)

    samples = await ble.diagnose_wifi(
        target.address,
        polls=args.polls,
        interval=args.interval,
        on_step=lambda line: print(f"  {_console.dim(line)}"),
    )
    print(f"\n  {_console.accent(ble.wifi_diagnosis(samples))}\n")
    print(_console.dim("  The robot is in pairing mode now. Run `whiskerless provision` to restore it.\n"))
    return 0


async def _cmd_provision(args: argparse.Namespace) -> int:
    from . import ble

    # Kept for the non-interactive path below, which defaults the SSID from it.
    # There is deliberately no "press enter to accept the existing setup" hint any
    # more: nothing this command still asks HAS a default. The broker and the CA
    # moved to `setup`, the network comes from the robot's own scan, and the
    # serial is per-robot — so the only prompt enter would have answered is the
    # password, where it sets an empty one.
    prior = _prior_robot()

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
    # The broker is asked ONCE, on the first robot, and remembered for the store.
    # Every robot here talks to the same broker behind the same CA — a genuinely
    # separate broker is a separate store, reached with WHISKERLESS_HOME.
    store = ProfileStore.from_env()
    # The store's own mode decides what "set up" means here. In `mutual` it means
    # a signing key, because every provision issues a certificate — the shape an
    # upgraded 0.1.3 store arrives in, and without this the run dies on a missing
    # ca.key deep inside, after the user has already put a robot into pairing
    # mode. In the other two, nothing is signed here and the trust anchor is
    # enough.
    ready = store.has_ca() if _stored_mode(store) is AuthMode.MUTUAL else store.has_ca_cert()
    if not store.has_broker() or not ready:
        # Deliberately does NOT offer to do it here. Between generating
        # certificates and a robot being able to use them, three files have to
        # reach the broker and it has to restart — and the robot is holding a
        # pairing window open the whole time.
        raise WhiskerlessError(
            "this machine is not set up yet — run `whiskerless setup` first. It "
            "establishes your broker and its certificates, which have to be "
            "installed on the broker before a robot can reach it"
        )
    broker = store.load_broker()
    host = broker.host
    # Unconditional: the guard above already refused a machine with no CA on
    # file, so there is no second case left. There used to be a fallback here
    # reading `--ca`, which `provision` no longer has — unreachable, and an
    # AttributeError the day something made it reachable.
    ca_pem = store.ca_path.read_text(encoding="utf-8")
    # Checked at every provision, not only when it was filed. An authority managed
    # elsewhere can expire between two robots, and writing it produces a robot that
    # cannot verify the broker — which costs another walk to the machine.
    _check_ca_cert(ca_pem)
    # Deliberately NOT asked here when there is a human to ask later. The robot
    # can list the networks IT can see, and asking before the BLE link is open
    # means asking someone to name a network from memory — which is how a robot
    # ends up provisioned onto an SSID it cannot reach, or a 5 GHz-only one it
    # cannot see, with nothing to show for it but a robot that never appears.
    ask_now = bool(args.wifi_ssid) or not sys.stdin.isatty()
    ssid = (
        _ask(
            "WiFi SSID: ", args.wifi_ssid, _check_ssid,
            default=prior.wifi_ssid or None if prior else None,
        )
        if ask_now
        else ""
    )
    wifi_pass = args.wifi_pass or ""
    if ssid and not wifi_pass and sys.stdin.isatty():
        wifi_pass = _ask_secret(f"WiFi password for {ssid!r}: ")

    store.assert_usable(broker)
    identity = _robot_identity(args, store, serial, broker.auth)
    config = ble.ProvisioningConfig(
        serial=serial, host=host, ca_pem=ca_pem, wifi_ssid=ssid, wifi_pass=wifi_pass,
        client_cert=identity.cert_pem if identity else None,
        client_key=identity.key_pem if identity else None,
    )

    # Said BEFORE the scan starts, because it is a physical prerequisite and the
    # window is short: the robot advertises only while Connect is held, so anyone
    # who learns this from the scan failing has already missed it. The tool knew
    # this — the scan returns on the first answer precisely to spend as little of
    # that window as possible — and never told the person holding the robot.
    # Shown for --address too: that still scans (filtered to one device) and then
    # connects, so the window matters exactly as much.
    #
    # "until it says connected", not "while this scans": the scan ENDS before the
    # link is opened, and somebody who releases at the end of the scan spends the
    # window in the gap — which is the failure `scan()` was rewritten to avoid.
    # The signal is the LIGHT, which is what Whisker's own documentation and this
    # command's own failure path both name. An earlier version of this hint said to
    # hold "until it beeps": the robot has no beep, so the one cue it gave was for
    # something that never happens, and the reader is left guessing during the only
    # step with a hard physical deadline.
    print(
        f"\n  Hold {_console.accent('Connect')} on the robot now until its light\n"
        f"  {_console.accent('BLINKS YELLOW')} (about three seconds) — that is pairing mode — and\n"
        "  keep holding until the numbered steps below start. It only\n"
        "  advertises while you hold, and the link is opened after the\n"
        "  scan finds it.\n"
    )
    # Said at the moment of the hold, because that is the only moment it can still
    # be avoided. Whisker documents the same behaviour for their own app
    # (litter-robot.com/support/article/litter-robot-4-not-connecting/): entering
    # onboarding mode makes the robot "forget its saved WiFi network". Confirmed on
    # hardware 2026-08-19 — a robot left in pairing mode never rejoins, is not even
    # ARP-resolvable from its own VLAN, and the mode never times out.
    _console.banner("HOLDING CONNECT WIPES THE ROBOT'S SAVED WIFI — FINISH THIS PROVISION")
    print(
        "  The robot forgets its network the moment it enters pairing mode — that\n"
        "  much is Whisker's own documented behaviour. On the unit we tested it did\n"
        "  not come back on its own: nothing timed the mode out, and no button we\n"
        "  tried left it. Assume only a completed provision restores it.\n\n"
        "  If you abandon this run, the robot stays off your network until you come\n"
        "  back with this laptop and finish one.\n"
    )
    # The scan is the one stretch a first-time user stares at with nothing
    # moving — indistinguishable from hung without a liveness row.
    with _console.progress("scanning for robots over BLE"):
        robots = await ble.scan(timeout=args.scan_timeout, address=args.address)
    if not robots:
        # HOLD, not tap. A tap toggles the robot's WiFi off (light goes white),
        # which looks like a dead robot and is the worse failure of the two.
        print(
            "no LR4 found advertising — HOLD the robot's Connect button for about three "
            "seconds, until its light BLINKS YELLOW (that is pairing mode), then rerun.\n"
            "If it is ALREADY blinking yellow it has forgotten its WiFi and is off your\n"
            "network until a provision completes — rerun this and finish it.\n"
            "Hold it, do not tap it: a short press toggles the robot's WiFi off instead.",
            file=sys.stderr,
        )
        return 1
    target = _pick_robot(robots, args.address)

    identity_note = (
        f"issued by your CA, CN={config.serial}"
        if broker.auth is AuthMode.MUTUAL
        else f"supplied by you, CN={pki.certificate_common_name(identity.cert_pem)}"
        if identity
        else "unchanged — the robot keeps the certificate it shipped with"
    )

    def _confirm_write(settled: ProvisioningConfig, mac: str | None) -> bool:
        """The one screen a first-time user reads carefully.

        Shown only once every value is known — the network is chosen over the
        open BLE link, so asking any earlier would print a blank WiFi row and ask
        somebody to approve a thing they had not chosen yet.
        """
        print()
        _console.banner("RE-PROVISION — this re-points the robot away from Whisker's cloud")
        # Firmware that will not answer the device-id read leaves this unset; a
        # literal "MAC None" beside the address is worse than no MAC at all.
        mac_note = _console.dim(f"(MAC {mac})") if mac else ""
        # Padded off ONE width, not per line: "identity" is the longest label and
        # hand-spacing the other four to match it is how the values ended up a
        # column apart from it.
        def row(label: str, value: str) -> str:
            return f"    {label:<9}{value}"

        print(row("robot", f"{_console.accent(target.address)} {mac_note}").rstrip())
        print(row("serial", _console.accent(settled.serial)))
        print(row("broker", _console.accent(settled.host)))
        print(row("wifi", _console.accent(settled.wifi_ssid)))
        print(row("identity", _console.accent(identity_note)))
        print(_console.dim("    reversible — re-onboard the robot in the Whisker app\n"))
        if args.dry_run:
            print(_console.dim(
                "  DRY RUN — the BLE connect, endpoint discovery and reads below are real;\n"
                "  nothing is written to the robot.\n"
            ))
        return bool(args.yes) or _confirm("Proceed? Type 'yes': ")

    # Numbered rather than bulleted: provisioning is a SEQUENCE whose order is
    # load-bearing, and when one step fails the useful question is which.
    #
    # The marker is deliberately NEUTRAL, not a tick. These callbacks carry no
    # status — some announce work about to happen, some warn — so a success mark
    # would put a green tick immediately above a failure, precisely when someone
    # is reading the sequence to find out what went wrong. Success is the closing
    # line's job, because only that knows.
    written = 0

    def _step(message: str) -> None:
        nonlocal written
        written += 1
        print(f"  {_console.dim(f'{written:>2}')} {_console.dim('▸')} {message}")

    result = await ble.provision_robot(
        target.address, config, dry_run=args.dry_run, on_step=_step,
        choose_network=lambda networks: _choose_network(networks, wifi_pass),
        confirm=_confirm_write,
    )
    print()
    # The abort check comes FIRST: declining a dry run is still a decline, and a
    # script reading the exit code should not be told it succeeded.
    if result.message.startswith("aborted"):
        print(result.message, file=sys.stderr)
        return 1
    if args.dry_run:
        print(result.message)
        return 0
    if not result.success:
        print(result.message, file=sys.stderr)
        return 1
    print(_console.accent(result.message))

    # Written only after the robot accepted it, so a failed run never leaves a
    # profile claiming a robot is reachable somewhere it is not — and the broker
    # only becomes the one every other command targets once a robot is actually
    # on it. An abort or a failed join must not retarget the whole machine.
    store.save_broker(broker)
    # Read BEFORE the save, because the save is what would make them equal. An
    # identity is reused whenever one is already on file and still current, so a
    # re-provision usually writes the certificate the store already had — and
    # telling someone their backup is missing a key it already contains teaches
    # them to ignore the notice.
    previous = (
        store.load_robot_identity(serial).cert_pem
        if store.has_robot_identity(serial)
        else None
    )
    if identity is not None:
        # Now: the robot has it, so the store recording it is a true statement.
        store.save_robot_identity(serial, identity)
    _save_profile(config, args, pki.issued_serial(identity) if identity else None)
    _remind_to_back_up(
        store, serial, identity is not None and identity.cert_pem != previous
    )
    return 0


async def _choose_network(
    networks: Sequence[DiscoveredNetwork], supplied_pass: str = ""
) -> tuple[str, str]:
    """Pick from what the ROBOT can see, then take that network's passphrase.

    Sorted strongest-first, because signal at the robot is the one thing the
    person provisioning cannot judge from where they are standing.
    """
    if not networks:
        # Hidden SSIDs are real and the robot joins them fine; it just cannot
        # list them. Falling back to typing beats refusing.
        print("  the robot saw no networks — type the name instead")
        ssid = _ask("WiFi SSID: ", None, _check_ssid)
        return ssid, supplied_pass or _ask_secret(f"WiFi password for {ssid!r}: ")

    # Legend, not a header row: two of the four columns are one character wide, so
    # anything aligned above them reads as noise. The signal is qualified as being
    # at the ROBOT because that is the whole reason this list is worth printing —
    # it is the one thing the person holding the laptop cannot judge from where
    # they are standing.
    print("\n  networks the robot can see, strongest first:")
    print(_console.dim(
        "   * = password required   |||| = signal AT THE ROBOT   ch = channel\n"
    ))
    for index, network in enumerate(networks):
        lock = "*" if network.secured else " "
        bars = _console.dim(("|" * network.bars).ljust(4))
        print(f"   {_console.dim(f'{index:>2}')}  {network.display:<32s} {lock} {bars} "
              f"{_console.dim(f'ch {network.channel}')}")
    print(f"   {_console.dim(' -')}  {_console.dim('my network is not listed — type its name (hidden SSID)')}\n")

    while True:
        try:
            answer = input(
                f"select a network by number (0-{len(networks) - 1}), "
                "or - to type a hidden one: "
            ).strip()
        except EOFError:
            raise WhiskerlessError("no network chosen (input ended)") from None
        if answer == "-":
            ssid = _ask("WiFi SSID: ", None, _check_ssid)
            break
        if answer.isdigit() and 0 <= int(answer) < len(networks):
            chosen = networks[int(answer)]
            # An open network has no passphrase, and the robot joins it with an
            # empty one. Asking anyway invites someone to invent an answer.
            if not chosen.secured:
                print(_console.dim("  open network — no password needed"))
                return chosen.ssid, ""
            ssid = chosen.ssid
            break
    return ssid, supplied_pass or _ask_secret(f"WiFi password for {ssid!r}: ")


def _ensure_trust_anchor(
    args: argparse.Namespace, store: ProfileStore, mode: AuthMode, bringing_client: bool = False
) -> None:
    """The CA certificate, for the two modes that do not sign with it.

    Both still need it. It is what the robot is told to trust, and without it a
    robot cannot verify the broker at all — the mode changes who issues the
    robot's own identity, not whether there is an authority behind the broker's.
    """
    if args.ca_key:
        # An explicit flag contradicting an explicit mode is worth stopping over.
        # Silently filing the key would leave a store that says its identities are
        # issued elsewhere while holding everything needed to issue them here, and
        # the next reader has no way to tell which is true.
        raise WhiskerlessError(
            f"--ca-key contradicts --auth {mode.value}: that mode exists so the "
            "signing key never reaches this machine. Drop the key, or use "
            "`--auth mutual` to have whiskerless issue certificates itself"
        )
    if mode is AuthMode.SUPPLIED and store.has_ca():
        # Switching an existing store over: `supplied` states that the signing key
        # is not on this machine, and a mode recorded as a fact has to be one.
        # `anonymous` makes no such claim and is left alone.
        #
        # MOVED, not deleted, and said that way on purpose: if the authority you
        # issue from turns out not to be this one, the copy here is the only thing
        # standing between you and re-provisioning every robot you own.
        raise WhiskerlessError(
            f"--auth supplied says the signing key never reaches this machine, but "
            f"{store.ca_key_path} is on it. Move that file somewhere safe first — "
            "keep it, do not delete it: if the authority you issue from is not this "
            "one, it is the only thing that can still sign for your robots"
        )
    if args.ca:
        brought = pki.read_cert(Path(args.ca))
        _check_ca_cert(brought)
        _refuse_a_different_ca(store, brought)
        store.save_ca_cert_only(brought)
        print(f"  CA certificate copied to {store.ca_path}")
    elif not store.has_ca_cert():
        if not sys.stdin.isatty():
            raise WhiskerlessError(
                f"--auth {mode.value} needs the CA certificate your robots are told "
                "to trust — pass --ca <file>, or run this in a terminal to be asked "
                "for it"
            )
        print()
        _console.banner("NO CERTIFICATE AUTHORITY ON THIS MACHINE")
        print(
            f"  In {mode.value} mode whiskerless does not issue certificates, but the\n"
            "  robot still has to be told which broker certificate to trust — so the\n"
            "  authority's certificate has to be here.\n"
        )
        # No EOFError handler: `_ask` already turns an input that ends into a
        # one-line error. The banner above has said what is needed, and a second
        # message wrapping the first would be unreachable either way.
        path = _ask("path to your CA certificate: ", None, _readable_path)
        brought = pki.read_cert(Path(path))
        _check_ca_cert(brought)
        store.save_ca_cert_only(brought)
        print(f"  CA certificate copied to {store.ca_path}")

    if mode is AuthMode.SUPPLIED and not (bringing_client or store.has_client()):
        # Nothing here can mint it, and a store in this mode with no identity of
        # its own reaches a listener asking for one and is refused — after
        # reporting that setup succeeded.
        raise WhiskerlessError(
            "--auth supplied needs this machine's own certificate too, since "
            "whiskerless cannot issue one: pass --client-cert and --client-key"
        )


def _stored_mode(store: ProfileStore) -> AuthMode:
    """This store's mode, or the default for a store too empty to have one.

    A machine with no broker on file has not been set up, and the caller says so
    in better words than `load_broker()` would — so the missing file is answered
    with the default rather than an exception raised from the wrong place.
    """
    return store.load_broker().auth if store.has_broker() else AuthMode.MUTUAL


def _robot_identity(
    args: argparse.Namespace, store: ProfileStore, serial: str, mode: AuthMode
) -> KeyPair | None:
    """What this robot will present to the broker, or None if it keeps its own.

    Stored, not minted per run. A robot re-provisioned — a new WiFi password is
    enough — stays the same client to the broker afterwards, so ACLs and log lines
    keyed to its certificate keep pointing at the same robot. And a supplied
    certificate has to be kept, because nothing here can produce another one.
    """
    supplied = bool(args.robot_cert or args.robot_key)
    if supplied and not (args.robot_cert and args.robot_key):
        raise WhiskerlessError("--robot-cert and --robot-key go together; supply both")

    if mode is AuthMode.ANONYMOUS:
        if supplied:
            raise WhiskerlessError(
                "--robot-cert contradicts this store's 'anonymous' mode, where robots "
                "keep the certificate they shipped with. Run `whiskerless setup "
                "--auth supplied` first if that has changed"
            )
        return None

    if supplied:
        pair = pki.read_pair(Path(args.robot_cert), Path(args.robot_key))
        _check_supplied_identity(store, pair, names=serial)
        # NOT written here. Whatever the store holds stays until the robot has
        # accepted the replacement — in `supplied` mode the old one cannot be
        # recreated, so an abort between here and the BLE write would destroy it
        # to install nothing.
        return pair

    if mode is AuthMode.SUPPLIED:
        if args.reissue:
            # Silently reusing the old one would answer "rotate this compromised
            # certificate" with "provisioned successfully" and the same certificate.
            raise WhiskerlessError(
                "--reissue has nothing to issue with in 'supplied' mode. Issue a "
                "replacement from your CA and pass it with --robot-cert and "
                "--robot-key"
            )
        if store.has_robot_identity(serial):
            held = store.load_robot_identity(serial)
            # Checked again, not trusted because it was checked once: a WiFi
            # password change is a re-provision, and a certificate that was in
            # date when it was filed may not be now. Writing it would report
            # success and hand the robot something the broker rejects.
            _check_supplied_identity(store, held, names=serial)
            return held
        raise WhiskerlessError(
            f"this store issues nothing itself ('supplied' mode) and has no "
            f"certificate on file for {serial} — pass --robot-cert and --robot-key "
            "with one signed by your CA"
        )

    stale = store.has_robot_identity(serial) and not pki.is_current(
        store.load_robot_identity(serial).cert_pem
    )
    if stale:
        # Free to replace and pointless to keep: this store signs, so an expired
        # cached certificate is a fresh one away, and writing the old one would
        # produce a robot the broker refuses.
        print("  the certificate held for this robot has expired — issuing another")
    elif args.reissue and store.has_robot_identity(serial):
        print("  replacing the certificate this store holds for this robot")
    return store.robot_identity(serial, reissue=args.reissue or stale, persist=False)


def _check_supplied_identity(
    store: ProfileStore, pair: KeyPair, *, for_robot: bool = True, names: str | None = None
) -> None:
    """Refuse anything that is not a usable client certificate.

    Everything checked here ends up written to the robot, where a mistake surfaces
    as a TLS handshake that names nothing, long after whoever supplied the file has
    walked away. One of them is worse than that: **a CA certificate is signed by
    the stored authority when the stored authority IS it**, so a signature check
    alone accepts `--robot-cert ca.crt --robot-key ca.key` and writes the signing
    key of the whole fleet into a litter box.
    """
    from cryptography import x509

    cert = _load_certificate(pair.cert_pem)
    try:
        basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound:
        basic = None
    if basic is not None and basic.ca:
        raise WhiskerlessError(
            "that is a certificate authority, not a certificate for one robot — "
            "provisioning writes the private key beside it to the robot, so this "
            "would hand your signing key to a litter box. Issue a client "
            "certificate from it instead"
            if for_robot
            else "that is a certificate authority, not a client certificate. Filing "
            "it here would leave the signing key on a machine whose mode says it "
            "never arrives — issue a client certificate from it instead"
        )
    now = datetime.now(UTC)
    if cert.not_valid_after_utc <= now:
        raise WhiskerlessError("that certificate has already expired")
    if cert.not_valid_before_utc > now:
        # Written to the robot it is refused until the hour it starts, and the
        # refusal says nothing about why — which is the whole class of failure
        # these checks exist to move forward to here.
        raise WhiskerlessError(
            f"that certificate is not valid until {cert.not_valid_before_utc:%Y-%m-%d %H:%M} "
            "UTC — the broker refuses it until then"
        )
    if names is not None:
        named = pki.certificate_common_name(pair.cert_pem)
        if named is None:
            print(
                f"  ! that certificate has no common name. Brokers using "
                f"`use_identity_as_username`\n    log and authorise by it, so {names} "
                "will not appear as itself.",
                file=sys.stderr,
            )
        elif named != names:
            raise WhiskerlessError(
                f"that certificate names {named}, not {names}. The broker takes the "
                "robot's username from it, so this robot would connect as another "
                "one — against another robot's ACLs, under another robot's name in "
                "the log"
            )
    if not pki.is_signed_by(pair.cert_pem, store.ca_path.read_text(encoding="utf-8")):
        raise WhiskerlessError(
            f"that certificate was not signed by the CA in {store.ca_path}, which is "
            "what the robot is told to trust — the broker would refuse it. Issue one "
            "from that authority, or point this store at the authority you issue from"
        )
    try:
        usages = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound:
        return
    if x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH not in usages:
        # Warned, not refused, and only when the extension is present to disagree
        # with: a broker checking EKU rejects it, and plenty do not. Refusing would
        # strand somebody whose CA issues certificates that work.
        print(
            "  ! that certificate is not marked for client authentication. Brokers "
            "that check\n    extended key usage will refuse it.",
            file=sys.stderr,
        )


def _read_client_pair(args: argparse.Namespace) -> KeyPair | None:
    """This machine's own identity, for somebody who issues it elsewhere.

    Read here and filed by the caller once the CA is on disk to check it against.
    Nothing is written in between, so a run that fails leaves the identity the
    store was already using exactly as it was.
    """
    if not (args.client_cert or args.client_key):
        return None
    if not (args.client_cert and args.client_key):
        raise WhiskerlessError("--client-cert and --client-key go together; supply both")
    return pki.read_pair(Path(args.client_cert), Path(args.client_key))


def _names_host(pem: str, host: str) -> bool:
    """Whether this certificate is for ``host``, by the rules TLS actually uses.

    Subject Alternative Name first and Common Name only as a fallback: modern
    issuers put nothing in the CN, so treating an empty one as "fine" passes a
    certificate that names some other broker — or nothing at all — and the failure
    lands at the robot as a verification error naming none of this.
    """
    from cryptography import x509

    cert = _load_certificate(pem)
    try:
        alt = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        alt = None
    if alt is not None:
        addresses = [str(n) for n in alt.get_values_for_type(x509.IPAddress)]
        dns = [str(n) for n in alt.get_values_for_type(x509.DNSName)]
        # A DNS or IP SAN is authoritative and the common name is not consulted —
        # but only those two types. A certificate carrying, say, a URI SAN and a
        # matching CN is accepted by every TLS stack, and treating any SAN at all
        # as authoritative would call it foreign and overwrite it, private key and
        # all.
        if addresses or dns:
            if host in addresses:
                return True
            return any(_dns_name_matches(name, host) for name in dns)
    return pki.certificate_common_name(pem) == host


def _dns_name_matches(pattern: str, host: str) -> bool:
    """One DNS name from a certificate against the host, the way TLS compares them.

    Case-insensitively, and honouring a single leftmost wildcard. Comparing the
    literal strings instead reports a perfectly good `*.example.lan` as unable to
    serve `mqtt.example.lan` — and this function's answer is printed as advice to
    replace the certificate, so a false negative sends somebody to re-issue one
    that was already correct.
    """
    pattern, host = pattern.lower().rstrip("."), host.lower().rstrip(".")
    if not pattern.startswith("*."):
        return pattern == host
    # One label, and never the bare domain: `*.example.lan` covers `a.example.lan`
    # and neither `example.lan` nor `a.b.example.lan`.
    suffix = pattern[1:]
    if not host.endswith(suffix):
        return False
    return "." not in host[: -len(suffix)] and bool(host[: -len(suffix)])


def _load_certificate(pem: str) -> x509.Certificate:
    """Parse a PEM certificate, as a one-line error rather than a traceback."""
    from cryptography import x509

    try:
        return x509.load_pem_x509_certificate(pem.encode())
    except ValueError as exc:
        raise WhiskerlessError(f"that is not a readable PEM certificate: {exc}") from exc


def _remind_to_back_up(store: ProfileStore, serial: str, new_identity: bool) -> None:
    """Say it after a provision, not only after setup.

    A provision adds material to the store that a backup taken before it does not
    have: the profile always, and a private key when this run actually issued one.
    In `supplied` mode that key cannot be produced again by anything here, so a
    backup from before it is not merely stale, it is missing the only copy.

    ``new_identity`` is whether the certificate CHANGED, not whether one exists.
    Identities are kept rather than minted per run, so re-provisioning a robot —
    to move it to a new WiFi password, say — usually rewrites the certificate the
    store already held, and announcing that as new material sends someone to
    re-take a backup that would be byte-identical.
    """
    what = f"{serial}'s certificate and profile" if new_identity else f"{serial}'s profile"
    where = Path.home() / "Documents"
    print(
        f"  {_console.dim('Back up again:')} {what} is new here.\n"
        f"  {_console.dim(f'    whiskerless backup {where}')}\n"
    )


def _resolve_auth_mode(args: argparse.Namespace, saved: Broker | None) -> AuthMode:
    """The mode this run should use: what was asked for, else what is on file.

    Defaulting to the stored value rather than to MUTUAL is the whole point of
    storing it. `setup --host <new address>` is a routine thing to run, and a
    default that overrode the file would silently move a cert-manager store back
    onto certificates whiskerless signs — the second time, not the first, which is
    the kind of change nobody goes looking for.
    """
    if args.auth:
        chosen = AuthMode(args.auth)
        if saved is not None and chosen is not saved.auth:
            print(
                f"  authentication mode: {_console.accent(saved.auth.value)} → "
                f"{_console.accent(chosen.value)}"
            )
        return chosen
    return saved.auth if saved is not None else AuthMode.MUTUAL


def _ensure_pki(
    args: argparse.Namespace,
    store: ProfileStore,
    host: str,
    mode: AuthMode,
    brought_client: KeyPair | None = None,
) -> None:
    """Make sure this machine can produce the identities its mode calls for.

    Returns nothing: there is one outcome that is not an exception — a store that
    can do what its mode says. It used to return whether signing was possible,
    because a trust-anchor-only store was a resting state the caller warned about;
    that state is now either a stated mode or an error.

    Everything here is idempotent. A CA is generated once and reused forever —
    regenerating would strand every robot already provisioned to trust the old
    one, which is a bench visit each.
    """
    if mode is not AuthMode.MUTUAL:
        _ensure_trust_anchor(args, store, mode, brought_client is not None)
        return

    if args.ca_key:
        if not args.ca:
            raise WhiskerlessError(
                "--ca-key needs --ca as well: the key signs certificates, and the "
                "certificate is what the robot is told to trust"
            )
        brought = pki.read_pair(Path(args.ca), Path(args.ca_key))
        _check_ca(brought)
        _refuse_a_different_ca(store, brought.cert_pem)
        store.save_ca(brought)
        if brought_client is None:
            store.client_identity()
        print(f"  using the CA you supplied, copied to {store.ca_path}")
        return

    if args.ca and not args.ca_key:
        # In THIS mode a certificate on its own is an unfinished setup: whiskerless
        # signs every identity here, and cannot. It was a supported resting state
        # before 0.2.0, which is why it reads like one — so the message names the
        # two modes where it is still exactly right, rather than implying the only
        # way forward is to hand over a key somebody deliberately keeps elsewhere.
        raise WhiskerlessError(
            "--ca needs --ca-key in 'mutual' mode: whiskerless signs each robot's "
            "certificate here, and that needs the key. Supply both, or say where "
            "identities come from instead — `--auth supplied` if you issue them "
            "elsewhere, `--auth anonymous` if robots keep the certificate they "
            "shipped with"
        )

    if store.has_ca():
        return
    if store.has_ca_cert():
        _resolve_trust_only(store, host)
        return
    if not sys.stdin.isatty():
        # --ca WITH --ca-key satisfies this; the pair is read above. Only a run
        # with neither a stored CA nor a supplied one reaches here, and it should
        # name the flags that fix it rather than die on a prompt nobody could have
        # answered — naming --ca alone just moves the failure one guard earlier.
        raise WhiskerlessError(
            "no certificate authority: the robot has to be told which broker "
            "certificate to trust, and gets a certificate of its own signed by it. "
            "Pass --ca and --ca-key together, or run this in a terminal to be "
            "offered one"
        )

    print()
    _console.banner("NO CERTIFICATE AUTHORITY ON THIS MACHINE")
    # Two options, not three. The robot verifies your broker against whatever is
    # written into its trust slot, so a certificate authority is not optional —
    # there is no provisioning without one. Whether the robot gets an identity of
    # its own is a CONSEQUENCE of handing over the signing key, asked below, not
    # a third choice here.
    print(
        "  Your robot has to be told which broker certificate to trust, and that\n"
        "  means a certificate authority. There is no way around it.\n\n"
        f"   {_console.dim(' 1')}  Generate one for me {_console.dim('(recommended)')}\n"
        f"   {_console.dim(' 2')}  I already have one — I will give you the files\n"
    )
    try:
        answer = input("  Which? [1]: ").strip()
    except EOFError as exc:
        raise WhiskerlessError(
            "a certificate authority is required and there was nobody to ask — "
            "pass --ca and --ca-key together"
        ) from exc
    if answer == "2":
        _import_ca(store)
        return

    with _console.progress("generating a certificate authority"):
        ca = pki.generate_ca()
        store.save_ca(ca)
        server = pki.issue_server(ca, host)
        broker = store.save_broker_certs(server)
        if brought_client is None:
            store.client_identity()
    _report_pki(store, broker)


def _report_foreign_server_cert(store: ProfileStore, host: str, mode: AuthMode) -> bool:
    """The broker's certificate in the modes where nothing here can issue one.

    Same authority, someone else's issuer. Left entirely alone: whiskerless has no
    key to sign a replacement with, and overwriting a certificate destroys the
    private key beside it — so the useful thing is to say what it has to be, and
    whether what is on file matches.
    """
    existing = store.broker_dir / "server.crt"
    if not existing.is_file():
        print(
            f"\n  In {mode.value} mode whiskerless does not issue your broker's\n"
            f"  certificate either. It has to be signed by the same authority as\n"
            f"  {store.ca_path}, and name {_console.accent(host)} — the robot checks\n"
            "  that name. Install it on the broker yourself.\n"
        )
        return False
    pem = pki.read_cert(existing)
    # Every way it can be wrong, because setup's next line tells somebody to
    # restart their broker with it — and each of these surfaces at the robot as a
    # handshake failure that names none of them.
    problems = []
    if not pki.is_signed_by(pem, store.ca_path.read_text(encoding="utf-8")):
        problems.append(f"it was not signed by the CA in {store.ca_path}")
    served = _load_certificate(pem)
    if served.not_valid_after_utc <= datetime.now(UTC):
        problems.append("it has expired")
    elif served.not_valid_before_utc > datetime.now(UTC):
        problems.append(
            f"it is not valid until {served.not_valid_before_utc:%Y-%m-%d %H:%M} UTC"
        )
    if not _names_host(pem, host):
        problems.append(
            f"it does not name {host}, and the robot verifies that name against the "
            "certificate"
        )
    key = store.broker_dir / "server.key"
    if not key.is_file():
        problems.append(f"{key} is not beside it, and a broker cannot serve one without it")
    else:
        try:
            pki.read_pair(existing, key)
        except WhiskerlessError:
            problems.append(f"{key} is not the key for it")
    if problems:
        detail = "\n    ".join(f"- {problem}" for problem in problems)
        print(
            f"  ! {existing} cannot serve this broker:\n    {detail}\n"
            f"    Replace it with one your authority signed for {host}.",
            file=sys.stderr,
        )
        return False
    return True


def _refresh_server_cert(store: ProfileStore, host: str) -> bool:
    """Keep the broker's certificate matching the broker. Returns whether it is usable.

    Two ways it can be wrong, and both look perfectly fine on disk while failing
    every handshake: named for an address the robot does not connect to, or
    signed by a CA the robots were never given.

    **Only a certificate that chains to OUR CA is ever overwritten.** That is the
    line, and it is deliberate: proving a chain is harder than it looks — an
    intermediate, or an RSASSA-PSS signature, reads as "not ours" to a check this
    simple. A false negative that only warns costs a confusing message; one that
    overwrites destroys somebody's certificate *and its private key*. So a
    foreign certificate is reported and left alone, always.

    Takes no `can_issue`: since 0.2.0 a store always holds a signing key by the
    time this runs — `_ensure_pki` resolves a certificate-without-a-key before
    anything gets here — so the branches for "cannot reissue" described a state
    that can no longer exist.
    """
    existing = store.broker_dir / "server.crt"
    if not existing.is_file():
        broker = store.save_broker_certs(pki.issue_server(store.load_ca(), host))
        print(f"  issued your broker's certificate for {_console.accent(host)} "
              f"in {broker}")
        return True
    try:
        pem = existing.read_text(encoding="utf-8")
    except OSError:
        return False
    ours = store.ca_path.read_text(encoding="utf-8") if store.has_ca_cert() else ""
    chains = bool(ours) and pki.is_signed_by(pem, ours)

    if not chains:
        # Not ours to replace. Say what is wrong and stop — the alternative is
        # deleting a private key on the strength of a heuristic.
        print(
            f"  ! {existing} is not signed by the CA in {store.ca_path}.\n"
            f"    The robots are given that CA, so they cannot verify a broker\n"
            f"    presenting this. Replace it with one your CA signed — whiskerless\n"
            f"    will not overwrite a certificate it did not issue.",
            file=sys.stderr,
        )
        return False
    if _names_host(pem, host) and pki.is_current(pem):
        return True
    # Ours and out of date is reissued rather than reported: this store can sign,
    # so the fix costs nothing, and advertising it for installation would send
    # somebody to restart their broker into handshakes that all fail.
    #
    # Overwriting destroys the private key beside it, so "does it name the broker"
    # has to be answered the way TLS answers it — a wildcard or a differently-cased
    # SAN is a certificate somebody placed here deliberately and it works.
    store.save_broker_certs(pki.issue_server(store.load_ca(), host))
    why = "it named another host" if not _names_host(pem, host) else "it was out of date"
    print(f"  reissued the broker certificate for {_console.accent(host)} ({why})")
    return True


def _resolve_trust_only(store: ProfileStore, host: str) -> None:
    """A store holding a CA certificate but not its key has to become one or the other.

    That state was supported until 0.2.0: the robot was told who to trust and kept
    its factory certificate, and the broker's listener stayed anonymous. Now that
    whiskerless issues every robot an identity, the key is required — and quietly
    carrying on is the worst option, because it looks identical to a working setup
    while silently declining to do the thing the version exists for.

    It is also, specifically, what an upgraded 0.1.3 store looks like: the CA
    certificate hoists across from the robot profiles, and the key was never in
    there to hoist. So this is the first thing many upgraders will meet.
    """
    if not sys.stdin.isatty():
        raise WhiskerlessError(
            f"{store.ca_path} is a certificate with no key, and in 'mutual' mode "
            "whiskerless issues each robot its own certificate. Pass --ca and "
            "--ca-key to supply the key for this authority, or say the key lives "
            "elsewhere on purpose with `--auth supplied`, or run this in a terminal "
            "to be offered a new authority"
        )

    print()
    _console.banner("THIS MACHINE HAS A CA CERTIFICATE BUT NOT ITS KEY")
    print(
        "  Your robots were told to trust this authority, and it is still here —\n"
        "  but signing a certificate for a robot needs its private key, and that\n"
        "  is not here.\n\n"
        f"   {_console.dim(' 1')}  I have the key — I will give you the file\n"
        f"   {_console.dim(' 2')}  Generate a new authority "
        f"{_console.dim('(every robot must be re-provisioned)')}\n"
    )
    # Named but not numbered: it is not a third answer to THIS question, it is a
    # different setup — and the two options above are the two that finish here.
    # Somebody who keeps their key elsewhere on purpose should not have to pick
    # "generate a new authority" to get out of a prompt aimed at somebody who
    # lost theirs.
    print(
        f"  {_console.dim('Neither? If the key lives elsewhere on purpose — cert-manager,')}\n"
        f"  {_console.dim('Vault, an offline root — rerun with')} "
        f"{_console.dim(_console.accent('--auth supplied'))}"
        f"{_console.dim(' and issue the')}\n"
        f"  {_console.dim('certificates there instead.')}\n"
    )
    try:
        answer = input("  Which? [1]: ").strip()
    except EOFError as exc:
        raise WhiskerlessError(
            "a signing key is required and there was nobody to ask — pass --ca "
            "and --ca-key"
        ) from exc

    if answer != "2":
        key_path = _ask("path to the CA private key: ", None, _readable_path)
        brought = pki.read_pair(store.ca_path, Path(key_path))
        _check_ca(brought)
        # The key has to belong to the certificate already on file, or every robot
        # out there is trusting something this store cannot sign for.
        _refuse_a_different_ca(store, brought.cert_pem)
        store.save_ca(brought)
        store.client_identity()
        print(f"  key filed with the certificate in {store.root / 'ca'}")
        return

    print(
        "\n  Every robot provisioned against the old authority stops being able to\n"
        "  verify your broker, and each needs re-provisioning at the machine.\n"
    )
    if _ask("type 'yes' to replace the authority: ", None, lambda v: v) != "yes":
        raise WhiskerlessError("left the existing certificate alone; nothing was changed")
    # Decided BEFORE the authority is replaced: afterwards the old server
    # certificate reads as foreign, so `_refresh_server_cert` would rightly refuse
    # to touch it — and setup would report success having left the broker with a
    # certificate nothing can verify.
    existing = store.broker_dir / "server.crt"
    retiring = store.ca_path.read_text(encoding="utf-8")
    ours_to_replace = True
    if existing.is_file():
        try:
            ours_to_replace = pki.is_signed_by(existing.read_text(encoding="utf-8"), retiring)
        except OSError:
            ours_to_replace = False

    with _console.progress("generating a certificate authority"):
        ca = pki.generate_ca()
        store.save_ca(ca)
        # The old client certificate was signed by the authority just replaced, so
        # it would be refused the moment the listener asks for one — while setup
        # reported success. Dropped so a new one is minted below.
        store.forget_client()
        store.client_identity()
        # Every robot's recorded certificate was signed by the retired authority
        # too. Left in place they read as current, and `robots` would show nothing
        # to re-provision — at exactly the moment everything needs it.
        store.forget_issued_certificates()
    print(f"\n  Certificate authority created in {_console.accent(str(store.root))}")
    if ours_to_replace:
        # It was issued by the authority just retired, so it is ours to replace —
        # and it has to be, or the broker keeps serving something signed by a CA
        # no robot will be given again.
        store.save_broker_certs(pki.issue_server(ca, host))
        _report_files(store)
    else:
        # Someone else's. Reported and left alone, because overwriting a
        # certificate destroys its private key with it.
        print(
            f"  ! {existing} was not issued by this machine, so it has been left\n"
            f"    alone — replace it with one your new CA signed before restarting\n"
            f"    your broker.",
            file=sys.stderr,
        )


def _import_ca(store: ProfileStore) -> None:
    """Take a CA the user already has, and file it where everything else looks.

    Copied under our own names rather than remembered by path: a path breaks when
    the USB stick is unplugged or the folder is tidied, and it breaks later, at a
    moment nobody connects to the decision made here.

    The key is not optional. Until 0.2.0 it could be skipped, leaving a store that
    could name a trust anchor but never sign for one — which reads as a working
    setup right up until the robot is standing in front of you.
    """
    cert_path = _ask("path to your CA certificate: ", None, _readable_path)
    print(
        "\n  And its private key. whiskerless issues a certificate for each robot\n"
        "  itself, so it signs with this — it never leaves this machine.\n"
    )
    key_path = _ask("path to the CA private key: ", None, _readable_path)
    brought = pki.read_pair(Path(cert_path), Path(key_path))
    _check_ca(brought)
    _refuse_a_different_ca(store, brought.cert_pem)
    store.save_ca(brought)
    # Without this the robot gets a certificate and the CLI does not, so a broker
    # running `require_certificate true` would refuse every command afterwards.
    store.client_identity()
    print(f"  CA copied to {store.root / 'ca'}")


def _refuse_a_different_ca(store: ProfileStore, incoming: str) -> None:
    """Never swap the CA out from under robots that already trust it.

    Replacing it would leave every provisioned robot trusting a certificate the
    broker no longer presents, and each rescue is a walk to the robot with a
    laptop. Rotating deliberately means starting a fresh store.
    """
    if not store.has_ca_cert():
        return
    if store.ca_path.read_text(encoding="utf-8").strip() == incoming.strip():
        return
    robots = ", ".join(p.display_name for p in store.list_profiles())
    raise WhiskerlessError(
        "this machine already has a different certificate authority"
        + (f", and {robots} already trust it" if robots else "")
        + f". Replacing it would strand them. To start over, move {store.root} "
        f"aside or point WHISKERLESS_HOME somewhere else"
    )


def _readable_path(raw: str) -> str:
    """A path that exists, checked at the prompt rather than five answers later."""
    path = Path(raw).expanduser()
    if not path.is_file():
        raise WhiskerlessError(f"no such file: {path}")
    return str(path)


def _check_ca(ca: KeyPair) -> None:
    """Refuse a CA that cannot work, warn about one that will bite later."""
    _check_ca_cert(ca.cert_pem)


def _check_ca_cert(cert_pem: str) -> None:
    """The half of the check that needs no private key.

    Split out for the modes where there is no key to bring: the "you handed me a
    server certificate" mistake and an expired authority are exactly as fatal
    when somebody else does the signing.
    """
    from cryptography import x509

    cert = _load_certificate(cert_pem)
    try:
        basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    except x509.ExtensionNotFound:
        basic = None
    if basic is None or not basic.ca:
        # The "I handed you my server certificate" mistake, which otherwise fails
        # much later as an unexplained TLS error.
        raise WhiskerlessError(
            "that certificate is not a certificate authority — it cannot sign anything"
        )
    if cert.not_valid_after_utc <= datetime.now(UTC):
        raise WhiskerlessError("that CA has already expired")
    if cert.not_valid_before_utc > datetime.now(UTC):
        # Stored, it makes every chain fail validation until that date — including
        # the broker's, at every robot that was given it.
        raise WhiskerlessError(
            f"that CA is not valid until {cert.not_valid_before_utc:%Y-%m-%d %H:%M} UTC — "
            "nothing it signs can be verified before then"
        )
    try:
        cert.extensions.get_extension_for_class(x509.KeyUsage)
    except x509.ExtensionNotFound:
        # Works for the robot's mbedTLS and then breaks our own CLI under Python
        # 3.13's VERIFY_X509_STRICT. Warned rather than refused: the robot half
        # still works, and refusing would strand someone whose CA serves them.
        # Worth saying, but NOT the failure it used to be: mqtt.py clears
        # VERIFY_X509_STRICT for exactly this shape, so whiskerless itself is
        # fine. Other tools that pin a CA are not necessarily so forgiving.
        print(
            "  note: this CA has no keyUsage extension. whiskerless handles that, and\n"
            "  the robot's mbedTLS accepts it — but other TLS clients on Python 3.13+\n"
            "  may reject it with 'CA cert does not include key usage extension'.",
            file=sys.stderr,
        )
    if (cert.not_valid_after_utc - datetime.now(UTC)).days < 365:
        print("  ! this CA expires within a year; renewing it means re-provisioning "
              "every robot", file=sys.stderr)


def _report_files(store: ProfileStore) -> None:
    """The three files a broker needs, and which directive each one goes with."""
    print("\n  Your broker needs three files:\n")
    for path, directive in (
        (store.ca_path, "cafile"),
        (store.broker_dir / "server.crt", "certfile"),
        (store.broker_dir / "server.key", "keyfile"),
    ):
        print(f"    {path}  {_console.dim('→')}  {directive}")


def _report_pki(store: ProfileStore, broker: Path) -> None:
    """Say what was made, where it goes, and what losing it costs."""
    print(f"\n  Certificate authority created in {_console.accent(str(store.root))}")
    # NOT the file list — `setup` prints that itself once everything is issued,
    # and printing it here as well showed the same three paths twice in one run.
    print(
        f"\n  {_console.accent('Back up ' + str(store.root) + ' somewhere safe.')}\n"
        "  It holds the key that signs certificates for your robots. Losing it does\n"
        "  not stop robots that already work — it costs you the ability to add or\n"
        "  re-provision one without visiting every robot you own.\n"
    )


def _prior_robot() -> RobotProfile | None:
    """One robot already here, to offer its WiFi network from. Nothing else is
    per-robot any more."""
    store = ProfileStore.from_env()
    known = store.list_profiles()
    if not known:
        return None
    default = store.get_default()
    return next((p for p in known if p.serial.value == default), known[0])


def _save_profile(
    config: ProvisioningConfig, args: argparse.Namespace, cert_serial: str | None
) -> None:
    store = ProfileStore.from_env()
    try:
        prior = store.load(config.serial)
    except ProfileError:
        prior = None
    if prior is None:
        profile = RobotProfile(
            serial=Serial(config.serial),
            name=args.name or "",
            wifi_ssid=config.wifi_ssid,
            cert_serial=cert_serial,
        )
    else:
        # Reprovisioning replaces only what provisioning collected. The name and
        # the litter reference somebody measured at the machine were never asked
        # for, so writing defaults over them would silently erase them.
        profile = replace(
            prior,
            serial=Serial(config.serial),
            name=args.name or prior.name,
            wifi_ssid=config.wifi_ssid,
            cert_serial=cert_serial or prior.cert_serial,
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
    # A robot we hold no certificate serial for either never got one from us, or
    # got one from an authority since replaced — the physical robot did not change,
    # so this must not claim "factory identity" for the second case. Either way the
    # certificate it presents is one this store cannot vouch for: it works against
    # an anonymous listener and is refused outright by
    # one that requires certificates — which is the arrangement this project now
    # recommends, so the two states have to be told apart somewhere. Here rather
    # than on every command: the CA prompt was made once-only for the same reason,
    # and this is the command whose job is saying what is on the machine.
    # In `anonymous` mode a robot without one of our certificates is the ARRANGEMENT,
    # not a robot to go and fix — flagging every robot in the fleet would train
    # somebody to ignore the one marker that means something.
    expects_identity = _stored_mode(store) is not AuthMode.ANONYMOUS
    factory = [p for p in known if p.cert_serial is None] if expects_identity else []
    for profile in known:
        marker = "*" if profile.serial.value == default else " "
        confirmed = "" if profile.serial.verified else "  (serial as typed, unconfirmed)"
        identity = (
            "  ← no identity from this store"
            if expects_identity and profile.cert_serial is None
            else ""
        )
        print(f" {marker} {profile.display_name:<20}{confirmed}{identity}")
    for name, why in broken:
        print(f" ! {name:<20} unreadable — {why}")
    if broken:
        print("\n  ! damaged — re-run `whiskerless provision`, or drop it with `whiskerless forget`")
    if factory:
        print(
            f"\n  ← {len(factory)} robot{'' if len(factory) == 1 else 's'} hold"
            f"{'s' if len(factory) == 1 else ''} no certificate this store issued —\n"
            "    either the one it shipped with, or one signed by an authority since\n"
            "    replaced. Either way a listener with `require_certificate true` refuses\n"
            "    it, and re-provisioning is the fix."
        )
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
    doomed: RobotProfile | None = None
    try:
        doomed = store.resolve(args.robot)
        name = doomed.display_name
    except ProfileError:
        # A profile too corrupt to load is precisely the one `forget` must
        # still be able to remove.
        name = Serial(args.robot).value
        if not (store.robots_dir / name).is_dir():
            raise
    # Named explicitly, because in `supplied` mode this store holds the only copy
    # and nothing here can issue another. Approving "only removes the saved broker
    # details" and losing a private key is not a confirmation, it is a surprise.
    holds_identity = store.has_robot_identity(Serial(args.robot))
    also = (
        " Its certificate and private key go with it, and this machine may hold the\n"
        "  only copy."
        if holds_identity and _stored_mode(store) is AuthMode.SUPPLIED
        else " Its certificate and private key go with it."
        if holds_identity
        else ""
    )
    if not args.yes and not _confirm(
        f"Forget {name}? This removes what this machine saved about it; the robot "
        f"keeps running.{also} Type 'yes': "
    ):
        print("aborted", file=sys.stderr)
        return 1
    store.forget(args.robot)
    print(f"forgot {name}")
    return 0


# --- backup and restore --------------------------------------------------------
_PASSWORD_ENV = "WHISKERLESS_BACKUP_PASSWORD"


async def _cmd_backup(args: argparse.Namespace) -> int:
    """Pack this machine's store into one file.

    The CA private key is the only thing in here that cannot be regenerated, and
    the bill for losing it arrives years later as a walk to every robot in the
    house with a laptop.
    """
    store = ProfileStore.from_env()
    if not _holds_a_setup(store):
        raise WhiskerlessError(
            f"nothing to back up in {store.root} — run `whiskerless setup` first"
        )
    # Asked before the password, so a destination this refuses does not cost
    # somebody a passphrase they typed twice.
    target = _backup_target(args)
    if target.resolve().is_relative_to(store.root.resolve()):
        # Otherwise each backup swallows the last one, and they grow until the
        # size ceiling stops them. Easy to do by accident: running the command
        # from inside the store is all it takes.
        raise WhiskerlessError(
            f"{target} is inside the store being backed up — write it somewhere else"
        )
    password = _backup_password(args)
    blob = backup.create(store.root, password=password)
    # A name we chose steps around what is already there; a name somebody typed
    # is honoured, and overwriting it has to be asked for.
    chosen_for_them = target.is_dir()
    destination = (
        _reserve_a_name(target, encrypted=password is not None) if chosen_for_them else target
    )
    if not chosen_for_them and destination.exists() and not args.force:
        raise WhiskerlessError(f"{destination} already exists — pass --force to overwrite it")
    try:
        _write_bytes_private(destination, blob)
    except OSError as exc:
        if chosen_for_them:
            # Only ever the placeholder this run just created. A destination
            # somebody named may be the good backup they are replacing.
            destination.unlink(missing_ok=True)
        raise WhiskerlessError(f"could not write {destination}: {exc.strerror or exc}") from exc

    # Read back what actually landed on disk rather than describing what was
    # meant to. It is the same write-then-verify discipline every setting write
    # uses, and it is worth more here than anywhere: an archive that cannot be
    # opened is discovered now, not on the day it is the only copy left.
    print(f"\n  wrote {_console.accent(str(destination))}  ({_human_size(len(blob))})\n")
    written = backup.read(backup.load(destination), password=password)
    _describe(written)
    _warn_if_the_ca_cannot_sign(written)
    if password is None:
        print("\n  ! Not encrypted. It holds the private key that signs certificates for\n"
              "    your robots — keep it where you would keep a password.\n")
    else:
        print("\n  Encrypted with the password you typed. Nothing can recover that password,\n"
              "  so the backup is worth exactly as much as your record of it.\n")
    return 0


async def _cmd_restore(args: argparse.Namespace) -> int:
    """Put a backup back, refusing to quietly replace a working setup."""
    store = ProfileStore.from_env()
    source = Path(args.path).expanduser() if args.path else _choose_backup()
    raw = backup.load(source)
    archive = backup.read(raw, password=_restore_password(backup.is_encrypted(raw)))
    found = archive.layout_version()
    if found > LAYOUT_VERSION:
        raise WhiskerlessError(
            f"this backup was written by a newer whiskerless (layout {found}; this build "
            f"understands {LAYOUT_VERSION}) — upgrade whiskerless and try again"
        )

    # Moved, never deleted. What is being displaced may be the only copy of a CA
    # key that robots in this house still trust. But "not empty" is not the same
    # as "worth keeping": running any command at all stamps a layout marker into
    # the store directory, and refusing to restore over that alone would send
    # somebody hunting for the setup they are certain they never made.
    occupied = store.root.is_dir() and any(store.root.iterdir())
    aside = _unused_name(store.root, "replaced") if occupied else None
    valuable = _holds_a_setup(store)
    if aside is not None and valuable and not args.force:
        raise WhiskerlessError(_occupied(store, archive, aside))
    _swap_in(archive, store.root, aside)
    moved = aside if valuable else None
    if aside is not None and not valuable:
        shutil.rmtree(aside, ignore_errors=True)

    print(f"\n  restored {_console.accent(str(store.root))} from {source}\n")
    # Re-read through the store so an older layout is migrated now, and so the
    # summary describes what later commands will actually see.
    restored = ProfileStore.from_env()
    _describe(archive)
    _warn_if_the_ca_cannot_sign(archive)
    if moved is not None:
        print(f"\n  what was here is at {_console.accent(str(moved))} — delete it once you are sure")
    # Only when they are actually in the backup. A store built around an imported
    # CA never generated a server certificate, and pointing somebody at files
    # that do not exist sends them hunting for something that was never there.
    if (restored.broker_dir / "server.crt").is_file():
        _report_files(restored)
        print()
    return 0


def _holds_a_setup(store: ProfileStore) -> bool:
    """Whether this store contains anything somebody would miss.

    Asked of the CONTENTS, never of the directory: running any command at all
    stamps a layout marker, so "there is a file in it" would call an untouched
    machine a setup — which would make `backup` report a successful copy of
    nothing, and `restore` refuse to write to a machine that has nothing on it.

    The CA key counts on its own, without its certificate. A store somebody has
    damaged is exactly when the one unregenerable file has to stay rescuable.
    """
    return bool(
        store.has_ca_cert()
        or store.ca_key_path.is_file()
        or store.has_broker()
        or store.list_profiles()
    )


def _swap_in(archive: backup.Archive, root: Path, aside: Path | None) -> None:
    """Lay the archive down beside the store, then swap it in with renames.

    Never written over the live store directly. Extraction takes as long as it
    takes and can run out of disk halfway; a rename is near-instant, so the
    window in which the machine has neither the old setup nor the new one is
    microseconds rather than the whole unpack. If the swap itself fails, the
    displaced store goes straight back.
    """
    staged = _unused_name(root, "incoming")
    try:
        archive.write_into(staged)
        if aside is not None:
            root.rename(aside)
            try:
                staged.rename(root)
            except OSError:
                aside.rename(root)
                raise
        else:
            staged.rename(root)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        raise WhiskerlessError(
            f"could not restore into {root}: {exc.strerror or exc}"
        ) from exc


def _warn_if_the_ca_cannot_sign(archive: backup.Archive) -> None:
    """Say so when the authority in an archive is not a usable pair.

    The container's own integrity checks prove the file opened, not that what
    came out of it works: a truncated or mismatched ``ca.key`` on the machine is
    copied faithfully into the backup and reported as a success. Warned rather
    than refused — a damaged store is precisely when a copy is still worth
    having, and the point is that somebody hears about it now instead of on the
    day it is the only copy left.
    """
    cert, key = archive.ca_cert_pem(), archive.text("ca/ca.key")
    if cert is None or key is None:
        return
    try:
        pki.check_pair(pki.KeyPair(cert_pem=cert, key_pem=key))
    except WhiskerlessError as exc:
        print(
            f"\n  ! this certificate authority cannot sign anything: {exc}\n"
            "    Robots already provisioned keep working; adding or re-provisioning "
            "one does not.",
            file=sys.stderr,
        )


def _describe(archive: backup.Archive) -> None:
    """The three things a person checks to know they grabbed the right backup."""
    ca = archive.ca_cert_pem()
    if ca is not None:
        name = "unreadable"
        with suppress(WhiskerlessError):
            name = pki.certificate_common_name(ca) or "unnamed"
        print(f"    certificate authority   {name}{'' if archive.files.get('ca/ca.key') else '  (certificate only, cannot issue)'}")
    broker = archive.broker()
    if broker is not None:
        print(f"    broker                  {broker}:{DEFAULT_TLS_PORT}")
    robots = archive.robots()
    if robots:
        print(f"    robots                  {', '.join(robots)}")


def _occupied(store: ProfileStore, archive: backup.Archive, aside: Path) -> str:
    """Why restoring over an existing store is refused, in the terms that matter.

    Which CA is on each side is the whole question: the same one makes this a
    dull overwrite, a different one silently strands every robot that trusts the
    one being displaced, and each rescue is a bench visit.
    """
    incoming = (archive.ca_cert_pem() or "").strip()
    current = store.ca_path.read_text(encoding="utf-8").strip() if store.has_ca_cert() else ""
    if not current:
        verdict = "It has no certificate authority of its own."
    elif current == incoming:
        verdict = "Its certificate authority is the same one, so no robot would be stranded."
    else:
        known = ", ".join(profile.serial.value for profile in store.list_profiles())
        verdict = (
            "Its certificate authority is a DIFFERENT one"
            + (f", and the robots set up here ({known}) trust it" if known else "")
            + " — they would stop trusting your broker until each is re-provisioned over BLE."
        )
    return (
        f"{store.root} already holds a setup — restoring would replace it. {verdict} "
        f"Pass --force to move it aside to {aside} and restore anyway"
    )


def _backup_target(args: argparse.Namespace) -> Path:
    """Where the archive should go — a directory, or a filename to use verbatim.

    Asked rather than assumed when nobody said. The whole point of a backup is
    that it ends up somewhere *else*, and silently dropping it in whatever
    directory the terminal happened to be sitting in is how it ends up on the
    same disk as the thing it is insuring. Seeing the default offered is what
    makes somebody type `~/Documents` instead.
    """
    if args.path:
        return Path(args.path).expanduser()
    if not sys.stdin.isatty():
        return Path.cwd()
    return Path(
        _ask("where should the backup go?", None, _writable_target, default=str(Path.cwd()))
    ).expanduser()


def _reserve_a_name(target: Path, *, encrypted: bool) -> Path:
    """Claim a free filename by creating it, rather than by looking at the folder.

    Looking and then writing leaves a window between the two: two backups into
    the same folder can both see the same candidate free, and the second's write
    would then discard the first — the exact loss the numbering exists to
    prevent. ``O_EXCL`` makes the claim and the check the same operation.
    """
    for _ in range(100):
        candidate = backup.unused_name(target, encrypted=encrypted)
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            continue  # somebody else took it between the look and the claim
        return candidate
    raise WhiskerlessError(f"could not find a free filename in {target}")


def _writable_target(raw: str) -> str:
    """A destination that can actually be written, checked while somebody can fix it."""
    path = Path(raw).expanduser()
    if path.is_dir():
        return str(path)
    if not path.parent.is_dir():
        raise WhiskerlessError(
            f"there is no directory {path.parent} — give an existing folder, or a "
            f"filename inside one"
        )
    return str(path)


def _choose_backup() -> Path:
    """Which file to restore, when the command was given no path.

    Offers what is in front of it. Whiskerless names its own archives, so the
    common case — you just copied one back onto a fresh machine — is a numbered
    list rather than somebody retyping a path with a date in it.
    """
    if not sys.stdin.isatty():
        raise WhiskerlessError("which backup? give the path to the file to restore")
    found = _backups_here()
    if found:
        print("\n  backups in this directory:\n")
        for index, path in enumerate(found, start=1):
            sealed = _console.dim("  (encrypted)") if path.suffix == ".enc" else ""
            print(f"   {_console.dim(f'{index:>2}')}  {path.name}{sealed}")
        print()

    def chosen(answer: str) -> str:
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            return str(found[int(answer) - 1])
        return _readable_path(answer)

    prompt = "which backup? (a number, or a path): " if found else "path to the backup file: "
    return Path(_ask(prompt, None, chosen)).expanduser()


def _backups_here() -> list[Path]:
    """Archives whiskerless wrote, in the current directory, newest first.

    Ordered by name, not by modification time. The names are timestamped, and
    that timestamp is the one that survived being copied here — mtime says when
    this particular copy landed, which on a machine somebody is restoring onto
    is usually "all of them, just now, in no order at all".

    Only our own naming, too: a wider sweep for `*.tar.gz` would offer somebody's
    holiday photos as a candidate restore, and the prompt still takes any path.
    """
    try:
        found = [path for path in Path.cwd().glob("whiskerless-backup-*") if path.is_file()]
        return sorted(found, key=_made_at, reverse=True)[:9]
    except OSError:
        return []


_BACKUP_NAME = re.compile(r"\Awhiskerless-backup-(\d{8})-(\d{6})(?:-(\d+))?\.")


def _made_at(path: Path) -> tuple[str, str, int, str]:
    """Sort key for a backup filename: when it was made, then its tie-breaker.

    The counter has to be read as a NUMBER and the timestamp has to end where
    the counter begins — plain lexicographic order gets both wrong. `-2` sorts
    before `-10`, and worse, the unsuffixed name of a pair sorts *after* its
    `-2` sibling because `.` follows `-` in ASCII, so the older of two backups
    made in the same second would be offered as the newest one. Restoring the
    wrong backup is not a mistake to make easy.

    Anything not matching sorts last, under its own name — it is a file
    somebody renamed, and guessing at when they meant is worse than listing it.
    """
    found = _BACKUP_NAME.match(path.name)
    if found is None:
        return ("", "", 0, path.name)
    return (found[1], found[2], int(found[3] or 1), path.name)


def _backup_password(args: argparse.Namespace) -> str | None:
    """The password to encrypt with, or None for a plain archive.

    Never silently plain. A backup's whole purpose is to live somewhere else —
    a USB stick, cloud storage — and this one contains a signing key, so leaving
    it in the clear has to be something somebody chose.
    """
    if args.no_password:
        return None
    supplied = os.environ.get(_PASSWORD_ENV)
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        raise WhiskerlessError(
            f"there is nobody here to ask for a password — set {_PASSWORD_ENV}, or pass "
            "--no-password to write the archive (including your CA private key) in the clear"
        )
    while True:
        first = _ask_secret("password to encrypt this backup (enter for none): ")
        if not first:
            return None
        if first == _ask_secret("again: "):
            return first
        print("  those do not match", file=sys.stderr)


def _restore_password(encrypted: bool) -> str | None:
    if not encrypted:
        return None
    supplied = os.environ.get(_PASSWORD_ENV)
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        raise WhiskerlessError(
            f"this backup is encrypted and there is nobody here to ask — set {_PASSWORD_ENV}"
        )
    return _ask_secret("password for this backup: ")


def _write_bytes_private(path: Path, data: bytes) -> None:
    """Replace ``path`` atomically, owner-readable only, durable on return.

    Truncating in place would destroy an existing backup before the replacement
    is written, so a full disk or an interrupted run leaves neither — in the one
    tool whose entire job is not losing things. ``mkstemp`` creates at 0600
    regardless of umask, so the archive is never briefly world-readable either.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)  # noqa: PTH105 - os-level rename for durability
    finally:
        temp_path.unlink(missing_ok=True)


def _unused_name(root: Path, label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = root.with_name(f"{root.name}.{label}-{stamp}")
    attempt = 2
    while candidate.exists():
        candidate = root.with_name(f"{root.name}.{label}-{stamp}-{attempt}")
        attempt += 1
    return candidate


def _human_size(count: int) -> str:
    return f"{count / 1024:.1f} KB" if count >= 1024 else f"{count} bytes"


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


def _ask_secret(prompt: str) -> str:
    """Ask for a passphrase without echoing it.

    Nothing is stored. The WiFi passphrase is the only secret whiskerless ever
    asks for, it is wanted once while somebody is standing at the robot, and
    every device setup on earth asks for it the same way.
    """
    return getpass.getpass(prompt)


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
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug (--debug does both)")
    parser.add_argument("--version", action="version", version=f"whiskerless {__version__}")
    parser.add_argument("--debug", action="store_true",
                        help="full traceback AND the request log (what to send with a bug report)")

    # People type `whiskerless state --debug`, not `whiskerless --debug state`, so
    # these have to work in both positions. SUPPRESS is load-bearing: a subparser
    # copies its parent's actions and writes their DEFAULTS over the namespace the
    # top-level parser already filled, so a plain default here would silently
    # discard a --debug given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="full traceback AND the request log (what to send with a bug report)")
    common.add_argument("-v", "--verbose", action="count", default=argparse.SUPPRESS,
                        help="-v info, -vv debug (--debug does both)")

    # Not required: a bare invocation prints an orientation instead of an
    # argparse usage error, which is the one thing a first-time user cannot use.
    sub = parser.add_subparsers(dest="command", parser_class=argparse.ArgumentParser)

    def add_parser(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    def add_conn(p: argparse.ArgumentParser) -> None:
        # Everything here defaults to None so "not given" stays distinguishable
        # from "given the same value the saved profile holds" — otherwise every
        # flag would silently override the stored profile with argparse defaults.
        # Only what identifies the robot and this client. The broker, its CA and
        # this machine's certificate all come from the store — see _link.
        p.add_argument("--serial", help="which robot (default: the only one saved, or `use`)")
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

    p_wifi = add_parser("wifi-toggle", "toggle the robot's WiFi (it may not come back)")
    add_conn(p_wifi)
    p_wifi.set_defaults(func=_cmd_wifi_toggle)

    p_power = add_parser("power", "toggle robot power (it may not come back)")
    add_conn(p_power)
    p_power.set_defaults(func=_cmd_power)

    p_diag = add_parser(
        "diagnose",
        "ask the robot why its WiFi will not hold (read-only, BLE; often inconclusive)",
    )
    p_diag.add_argument("--address", help="BLE MAC to target directly (skip the picker)")
    p_diag.add_argument("--scan-timeout", type=float, default=15.0)
    p_diag.add_argument("--polls", type=int, default=8, help="how many status reads to take")
    p_diag.add_argument("--interval", type=float, default=3.0, help="seconds between reads")
    p_diag.add_argument("--yes", action="store_true", help="skip the pairing-mode confirmation")
    p_diag.set_defaults(func=_cmd_diagnose)

    p_prov = add_parser("provision", "re-provision a robot onto your broker over BLE")
    p_prov.add_argument(
        "--serial",
        help="robot serial: the unhyphenated LR4C… label line, not the LR4-…-US model "
        "(prompted if omitted)",
    )
    p_prov.add_argument("--wifi-ssid", help="WiFi SSID; omit it to choose from the networks the ROBOT can see")
    p_prov.add_argument("--wifi-pass", default=None, help="WiFi password (prompted securely if omitted)")
    p_prov.add_argument("--address", help="BLE MAC to target directly (skip the picker)")
    p_prov.add_argument("--scan-timeout", type=float, default=15.0)
    p_prov.add_argument("--dry-run", action="store_true", help="scan/connect and print steps, write nothing")
    p_prov.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_prov.add_argument("--name", help="what to call this robot afterwards, e.g. 'Upstairs'")
    p_prov.add_argument("--robot-cert", help="a certificate you issued for THIS robot, from your CA")
    p_prov.add_argument("--robot-key", help="the matching private key for --robot-cert")
    p_prov.add_argument(
        "--reissue", action="store_true",
        help="replace the certificate this store holds for the robot instead of reusing it",
    )
    p_prov.set_defaults(func=_cmd_provision)

    p_setup = add_parser("setup", "prepare this machine: your broker and its certificates")
    p_setup.add_argument("--host", help="broker IP or hostname the robots will publish to")
    p_setup.add_argument("--ca", help="use this CA certificate instead of generating one (needs --ca-key)")
    p_setup.add_argument("--ca-key", help="its private key — required: every robot gets a certificate signed by it")
    p_setup.add_argument("--client-cert", help="this machine's client certificate, if you issue your own")
    p_setup.add_argument("--client-key", help="the matching private key for --client-cert")
    p_setup.add_argument(
        "--auth", choices=[m.value for m in AuthMode],
        help="who issues the certificates robots present: mutual (default, whiskerless "
             "signs them), supplied (you hand them over), anonymous (robots keep the one "
             "they shipped with). Kept until you change it.",
    )
    p_setup.set_defaults(func=_cmd_setup)

    p_robots = add_parser("robots", "list the robots set up on this machine")
    p_robots.set_defaults(func=_cmd_robots)

    p_use = add_parser("use", "choose which robot commands act on by default")
    p_use.add_argument("robot", help="serial of a robot from `whiskerless robots`")
    p_use.set_defaults(func=_cmd_use)

    p_forget = add_parser("forget", "remove a robot's saved details from this machine")
    p_forget.add_argument("robot", help="serial of a robot from `whiskerless robots`")
    p_forget.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_forget.set_defaults(func=_cmd_forget)

    p_backup = add_parser("backup", "save this machine's setup (including the CA) to one file")
    p_backup.add_argument("path", nargs="?",
                          help="where to write it — a directory, or a filename (prompted if omitted)")
    p_backup.add_argument("--no-password", action="store_true",
                          help="write it unencrypted — the CA private key will be in the clear")
    p_backup.add_argument("--force", action="store_true",
                          help="overwrite the file you named (a generated name never collides)")
    p_backup.set_defaults(func=_cmd_backup)

    p_restore = add_parser("restore", "put a backup back on this machine")
    p_restore.add_argument("path", nargs="?",
                           help="the backup file to restore (prompted if omitted)")
    p_restore.add_argument("--force", action="store_true",
                           help="move an existing setup aside and restore over it")
    p_restore.set_defaults(func=_cmd_restore)

    return parser


def _report_migration() -> None:
    """Say it once, on the run that moved a pre-0.2.0 store.

    That run is the only moment anything knows for certain somebody is upgrading
    rather than starting fresh, and 0.2.0 changed things about their setup they
    did not ask for: the store moved, broker credentials stopped existing, and
    the better arrangement — a certificate per robot — is one they will otherwise
    never learn is available, because a trust-anchor-without-a-key looks exactly
    like a deliberate choice to everything downstream.
    """
    if not profiles.MIGRATED_FROM_LEGACY:
        return
    # Cleared as it is said, so this is once per MIGRATION rather than once per
    # process. A CLI run is a process either way; anything embedding this would
    # otherwise repeat the notice for every command after the first.
    discarded = profiles.MIGRATED_DISCARDED_BROKERS
    moved_to = profiles.MIGRATED_TO
    kept_broker = profiles.MIGRATED_BROKER
    # All four, not just the flag: an embedder migrating two stores in one process
    # would otherwise repeat the first store's discarded brokers against the second.
    profiles.MIGRATED_FROM_LEGACY = False
    profiles.MIGRATED_DISCARDED_BROKERS = ()
    profiles.MIGRATED_TO = None
    profiles.MIGRATED_BROKER = None
    # The path is captured when the rename happens, not looked up again here:
    # `from_env()` would re-run a migration that has just failed, and the second
    # exception escapes main() in place of the one-line error it already printed.
    # A store opened through WHISKERLESS_HOME is hoisted where it stands, so
    # there is no move to announce and claiming one sends the reader looking for
    # a directory that was never created.
    opening = (
        f"\n  Moved your settings to {_console.accent(str(moved_to))}.\n"
        if moved_to
        else "\n  Upgraded your settings to the 0.2.0 layout.\n"
    )
    print(
        opening + "  Your robots are untouched and still work.\n\n"
        "  Two things changed that you may care about:\n"
        "    * broker usernames and passwords are gone — everything authenticates\n"
        "      by certificate now, so a broker that demands one will refuse this CLI\n"
        "    * whiskerless issues each robot its own certificate now, which needs\n"
        "      your CA's private key. If you still have it, `whiskerless setup`\n"
        "      will ask for it; if not, it offers a new authority, and every robot\n"
        "      then needs re-provisioning plus a change on the broker\n\n"
        '  Neither is urgent. See "Upgrading from 0.1.3" in the README.\n',
        file=sys.stderr,
    )
    if discarded:
        # One store, one broker. Before layout 1 the address lived on each robot,
        # so this is the only moment the discarded ones can be reported at all.
        #
        # Reported rather than asked: this runs inside from_env(), before the
        # command the user typed, where a script has nobody to answer a prompt.
        # The choice is also a single field to change and costs no robot, unlike
        # the CA question, which does prompt because getting it wrong strands the
        # fleet.
        others = ", ".join(discarded)
        print(
            f"  ! More than one broker was named across your robots.\n"
            f"    kept      {kept_broker or '(none)'}\n"
            f"    discarded {others}\n\n"
            "    A store holds one broker. To change it, no robot affected:\n"
            "      whiskerless setup --host <address>\n"
            "    For separate brokers, use a separate store:\n"
            "      WHISKERLESS_HOME=<dir> whiskerless provision\n",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    finally:
        _report_migration()


def _main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    debug = args.debug or bool(os.environ.get("WHISKERLESS_DEBUG"))
    # --debug turns on debug LOGGING too. It used to control tracebacks alone,
    # which is not what the name promises: a provisioning failure was reproduced
    # with --debug and produced no request log at all, because that lived behind
    # -vv. The one flag anybody reaches for in a bug report now gives the whole
    # picture.
    level = logging.DEBUG if debug or args.verbose > 1 else (
        logging.INFO if args.verbose == 1 else logging.WARNING
    )
    # With a clock. Provisioning fails by running out of the robot's pairing
    # window, and a log with no timestamps cannot answer where the seconds went.
    #
    # OUR namespace only — the root stays quiet. bleak's backends log the exact
    # buffer handed to write_gatt_char, so a root-level DEBUG would print the WiFi
    # passphrase and every private-key chunk verbatim, straight past the redaction
    # in transport.py, and into the log this flag tells people to attach to a bug
    # report. Their chatter never found a bug here either; ours did.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("whiskerless").setLevel(level)
    if level <= logging.DEBUG:
        print(
            "  the log below carries network names and this robot's identifiers "
            "(no passwords or keys) — read it before sharing\n",
            file=sys.stderr,
        )
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
