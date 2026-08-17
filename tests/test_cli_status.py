"""The one-shot derived view, the manual calibration it reads, and Reset.

What these pin is the honesty of a one-shot: `status` answers from a single
FRESH document plus what a person measured, says plainly when it has no answer,
and never implies it knows the things that take a listener running for days.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from whiskerless.cli import main
from whiskerless.devices.litter_robot_4.models import LitterRobot4State
from whiskerless.devices.litter_robot_4.protocol import ActivityMessage, StateMessage
from whiskerless.profiles import Broker, ProfileStore, RobotProfile, Serial

SERIAL = "LR4C123456"
IDLE = {
    "robotStatus": 4,
    "catDetect": 0,
    "litterLevel": 446,
    "DFILevelPercent": 68,
    "odometerCleanCycles": 8099,
    "espFirmware": "1.1.75",
    "cleanCycleWaitTime": 7,
    "wifiRssi": -77,
}


class FakeLink:
    """A link that answers one state document, as the robot does."""

    document: ClassVar[dict[str, object]] = dict(IDLE)
    published: ClassVar[list[str]] = []
    stream: ClassVar[str] = "state"
    #: A document already sitting in the queue when the command connects.
    queued: ClassVar[dict[str, object] | None] = None
    requested: ClassVar[bool] = False

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self) -> FakeLink:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def request_state(self) -> None:
        FakeLink.requested = True

    async def publish(self, command: Any, *, allow_dangerous: bool = False) -> None:
        FakeLink.published.append(command.code)

    async def messages(self) -> Any:
        if FakeLink.queued is not None and not FakeLink.requested:
            # The robot's own periodic push, already waiting to be read.
            doc = FakeLink.queued
            FakeLink.queued = None
            yield StateMessage(state=LitterRobot4State.from_state_doc(doc), raw={})
            return
        if FakeLink.stream == "silent":
            await asyncio.sleep(0.05)  # outlives the timeout the command passes
            return
        if FakeLink.stream == "activity":
            # A robot that talks without answering: the stream ENDS, no timeout.
            yield ActivityMessage(readings=[], raw={})
            return
        raw = json.dumps(FakeLink.document)
        yield StateMessage(state=LitterRobot4State.from_state_doc(json.loads(raw)), raw={})


@pytest.fixture(scope="module")
def _cli_loop() -> Any:
    """See tests/test_cli.py — `main` must not close the session's current loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _no_broker(_cli_loop: Any) -> Any:
    FakeLink.document = dict(IDLE)
    FakeLink.published = []
    FakeLink.stream = "state"
    FakeLink.queued = None
    FakeLink.requested = False
    with (
        patch("whiskerless.cli.asyncio.run", _cli_loop.run_until_complete),
        patch("whiskerless.cli.LitterRobot4Link", FakeLink),
    ):
        yield


@pytest.fixture
def saved() -> ProfileStore:
    store = ProfileStore.from_env()
    store.save_broker(Broker(host="192.0.2.10"))
    store.save(RobotProfile(serial=Serial(SERIAL), name="Upstairs"))
    return store


# --- status -------------------------------------------------------------------
def test_status_reports_the_robot_in_plain_terms(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "Upstairs" in out
    assert "status" in out and "ready" in out
    assert "waste drawer" in out and "68%" in out
    assert "446 mm" in out


def test_status_says_what_a_one_shot_cannot_know(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A command that silently omitted cat weight would read as "no cat weight"."""
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "need a listener" in out
    assert "Home Assistant" in out


def test_status_names_an_uncalibrated_robot_as_uncalibrated(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--serial", SERIAL]) == 0
    assert "not calibrated" in capsys.readouterr().out


def test_status_uses_the_calibration_a_person_measured(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    saved.save(replace(saved.load(SERIAL), litter_full_mm=446))
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "446 mm when full" in out
    # 446 mm was declared the line, which the cloud's curve pins to 90%.
    assert "90%" in out


def test_status_reports_a_silent_robot_rather_than_inventing_one(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeLink.stream = "silent"
    assert main(["status", "--serial", SERIAL, "--timeout", "0.01"]) == 1
    assert "no state document" in capsys.readouterr().err


# --- calibrate ----------------------------------------------------------------
def test_calibrate_full_stores_the_current_distance(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["calibrate", "full", "--serial", SERIAL]) == 0
    assert saved.load(SERIAL).litter_full_mm == 446
    assert "446 mm" in capsys.readouterr().out


def test_calibrate_empty_stores_the_other_end(saved: ProfileStore) -> None:
    assert main(["calibrate", "empty", "--serial", SERIAL]) == 0
    stored = saved.load(SERIAL)
    assert stored.litter_empty_mm == 446
    assert stored.litter_full_mm is None, "the two points are independent"


def test_calibrate_refuses_a_reading_the_robot_is_not_making(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mid-cycle the sensors see the globe, not the litter — capturing that would
    bake a garbage reference in permanently."""
    FakeLink.document = {**IDLE, "robotStatus": 10}
    assert main(["calibrate", "full", "--serial", SERIAL]) == 1
    assert "not reporting a usable litter distance" in capsys.readouterr().err
    assert saved.load(SERIAL).litter_full_mm is None


def test_calibrate_needs_somewhere_to_keep_it(capsys: pytest.CaptureFixture[str]) -> None:
    """A broker to reach, but nothing saved for this robot, so there is no profile
    to write the measurement into."""
    from whiskerless.profiles import Broker, ProfileStore

    ProfileStore.from_env().save_broker(Broker(host="192.0.2.10"))
    assert main(["calibrate", "full", "--serial", SERIAL]) == 1
    assert "nowhere to keep a calibration" in capsys.readouterr().err


# --- panel-reset --------------------------------------------------------------
def test_panel_reset_presses_the_button(saved: ProfileStore) -> None:
    assert main(["panel-reset", "--serial", SERIAL]) == 0
    assert FakeLink.published == ["0x02010401"]


def test_status_survives_a_stream_that_never_answers(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The robot talked — just not about its state. Ending the stream without a
    document is not the same as timing out, and both mean the same to a user."""
    FakeLink.stream = "activity"
    assert main(["status", "--serial", SERIAL]) == 1
    assert "no state document" in capsys.readouterr().err


def test_status_shows_both_calibration_points_when_they_exist(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    saved.save(replace(saved.load(SERIAL), litter_full_mm=430, litter_empty_mm=486))
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "430 mm when full" in out and "486 mm when empty" in out


def test_calibrate_reports_a_silent_robot(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeLink.stream = "silent"
    assert main(["calibrate", "full", "--serial", SERIAL, "--timeout", "0.01"]) == 1
    assert "no state document" in capsys.readouterr().err
    assert saved.load(SERIAL).litter_full_mm is None


def test_a_hand_edited_calibration_loses_the_calibration_not_the_robot(
    saved: ProfileStore,
) -> None:
    """An unreachable profile is a far worse outcome than an unanchored percentage."""
    path = ProfileStore.from_env().robots_dir / SERIAL / "profile.json"
    raw = json.loads(path.read_text())
    raw["litter_full_mm"] = "about four hundred"
    path.write_text(json.dumps(raw))

    stored = saved.load(SERIAL)
    assert stored.litter_full_mm is None


def test_status_never_reports_the_globe_fault_field_as_an_all_clear(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The field read 0 through a live 50-minute fault, so a one-shot that
    printed 'globe motor fault: 0' would be answering a question it cannot."""
    FakeLink.document = {**IDLE, "globeMotorFaultStatus": 0}
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "globe motor fault" not in out
    assert "motor faults" in out, "and it says why it is silent"


def test_status_does_report_a_fault_the_field_admits_to(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeLink.document = {**IDLE, "globeMotorFaultStatus": 1}
    assert main(["status", "--serial", SERIAL]) == 0
    assert "globe motor fault" in capsys.readouterr().out


def test_an_impossible_stored_calibration_does_not_break_every_command(
    saved: ProfileStore,
) -> None:
    """JSON accepts 1e400; Python parses it to infinity and int() gives up."""
    path = ProfileStore.from_env().robots_dir / SERIAL / "profile.json"
    path.write_text(path.read_text().replace('"litter_full_mm": null', '"litter_full_mm": 1e400'))

    stored = saved.load(SERIAL)
    assert stored.litter_full_mm is None


def test_status_marks_a_reading_taken_while_a_cat_is_in_the_globe(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ToF measures whatever is in front of it — a captured visit read 253 mm
    against a 428-462 mm bed — and a one-shot is whatever moment you asked in."""
    FakeLink.document = {**IDLE, "catDetect": 1, "litterLevel": 253}
    assert main(["status", "--serial", SERIAL]) == 0
    assert "not a clean reading" in capsys.readouterr().out


def test_calibrate_refuses_a_distance_no_litter_bed_can_be_at(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Settled and empty by status, but 253 mm is a cat's back. A reference is
    permanent, so physics gets a vote as well as the status flags."""
    FakeLink.document = {**IDLE, "litterLevel": 253}
    assert main(["calibrate", "full", "--serial", SERIAL]) == 1
    assert "outside the range a litter bed can occupy" in capsys.readouterr().err
    assert saved.load(SERIAL).litter_full_mm is None


def test_a_stored_distance_in_kilometres_is_damage_not_calibration(
    saved: ProfileStore,
) -> None:
    """JSON accepts a thousand-digit integer; int() takes it and the first float
    division that touches it overflows."""
    path = ProfileStore.from_env().robots_dir / SERIAL / "profile.json"
    path.write_text(path.read_text().replace('"litter_full_mm": null', f'"litter_full_mm": {10**40}'))

    assert saved.load(SERIAL).litter_full_mm is None


def test_calibrate_refuses_a_pair_that_cannot_be_a_scale(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """More litter means a shorter distance, so empty must read FARTHER than
    full. Swapped, the percentage silently ignores the pair while status calls
    the robot calibrated."""
    saved.save(replace(saved.load(SERIAL), litter_full_mm=470))
    FakeLink.document = {**IDLE, "litterLevel": 446}  # "empty" nearer than "full"

    assert main(["calibrate", "empty", "--serial", SERIAL]) == 1
    assert "cannot be right" in capsys.readouterr().err
    assert saved.load(SERIAL).litter_empty_mm is None, "and nothing was saved"


def test_status_does_not_blame_calibration_for_a_number_it_did_not_make(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Some firmware publishes its own percentage, which outranks any reference
    we hold — "not calibrated" would be answering a different question."""
    FakeLink.document = {**IDLE, "litterLevelPercentage": 62}
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "reports its own percentage" in out
    assert "not calibrated" not in out


def test_calibrate_refuses_a_span_wider_than_the_globe_holds(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both readings can sit inside the plausible band and still be an
    impossible PAIR: the globe holds a couple of inches of litter."""
    saved.save(replace(saved.load(SERIAL), litter_full_mm=410))
    FakeLink.document = {**IDLE, "litterLevel": 525}

    assert main(["calibrate", "empty", "--serial", SERIAL]) == 1
    assert "only holds so much litter" in capsys.readouterr().err
    assert saved.load(SERIAL).litter_empty_mm is None


def test_status_does_not_call_a_settled_robot_unsettled(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A document with no distance is missing telemetry, not a cat in the globe."""
    FakeLink.document = {k: v for k, v in IDLE.items() if k != "litterLevel"}
    assert main(["status", "--serial", SERIAL]) == 0
    assert "not settled" not in capsys.readouterr().out


def test_status_refuses_to_present_a_hand_edited_scale_as_calibration(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A profile is a file on disk. A pair `calibrate` would have refused must
    not come back as fact through the other door."""
    saved.save(replace(saved.load(SERIAL), litter_full_mm=470, litter_empty_mm=446))
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "stored calibration is unusable" in out
    # And it is not quietly used to compute the percentage either.
    assert "446 mm when full" not in out


def test_status_rejects_a_stored_reference_no_litter_bed_could_produce(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """300 mm is a cat's back, not a litter bed. The store keeps it (it is a
    plausible number); the thing that reads it decides whether it is a scale."""
    saved.save(replace(saved.load(SERIAL), litter_full_mm=300))
    assert main(["status", "--serial", SERIAL]) == 0
    out = capsys.readouterr().out
    assert "stored calibration is unusable" in out
    assert "300 mm" in out


def test_calibrate_ignores_a_document_that_predates_the_request(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The robot pushes state on its own cadence, and `calibrate` runs seconds
    after someone changed the globe. A queued document describes the globe they
    just changed — pinning a permanent reference to it is the whole hazard."""
    FakeLink.queued = {**IDLE, "litterLevel": 470}  # before the fill
    FakeLink.document = {**IDLE, "litterLevel": 430}  # what they filled it to

    assert main(["calibrate", "full", "--serial", SERIAL]) == 0
    assert saved.load(SERIAL).litter_full_mm == 430


def test_calibrate_can_repair_a_calibration_that_cannot_be_a_scale(
    saved: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """`status` tells the user to re-run this command; validating the new reading
    against the bad endpoint would make that advice impossible to follow."""
    saved.save(replace(saved.load(SERIAL), litter_full_mm=470, litter_empty_mm=446))
    FakeLink.document = {**IDLE, "litterLevel": 430}

    assert main(["calibrate", "full", "--serial", SERIAL]) == 0
    stored = saved.load(SERIAL)
    assert stored.litter_full_mm == 430
    assert stored.litter_empty_mm is None, "starting over means starting over"
    assert "could not be a scale, so it was cleared" in capsys.readouterr().out
