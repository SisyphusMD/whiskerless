"""The facts a Litter-Robot 4 never publishes, derived from what it does.

The state document is a snapshot of registers. Everything a person actually
wants to know that is not literally in it — how much the cat weighed, when the
last visit was and how long it ran, whether a hopper is attached and how full,
when the drawer last moved, whether the globe motor is faulted, whether
something has been sitting on the scale too long — has to be assembled over
time from the activity stream and from transitions between snapshots.

That assembly is protocol knowledge, so it lives here rather than in any one
consumer. Home Assistant was the only consumer for a while and grew all of it;
the cost was that the CLI could not show anything Home Assistant showed without
a second implementation that would drift.

**The contract.** :func:`apply_message` is a reducer::

    (DerivedState, message, now) -> Update(state, changed, effects)

It is pure: no I/O, no clock of its own, no imports from any consumer. The
returned state is a new object, so a caller that ignores an update keeps the
one it had. Anything that must OUTLIVE the process — the learned scales, the
last fill gauge, which capabilities this robot has proven — comes back as an
*effect* describing what happened, and the caller decides where to write it.
The library owns the logic; the consumer owns the storage.

**One clock, and it is the wall clock.** Every stamp here is a real datetime
supplied by the caller. A monotonic clock cannot be persisted, cannot be
compared across a restart, and reads near zero at boot — which silently
discarded the first reading after every start, because it looked like it
arrived seconds after a sample that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, TypeAlias

from . import const as lr4
from .calibration import (
    HOPPER_CORROBORATION,
    HOPPER_PLAUSIBLE,
    LITTER_CORROBORATION_MM,
    LITTER_MAX_SPAN_MM,
    LITTER_PLAUSIBLE_MM,
    Learned,
    hopper_is_empty,
    hopper_percent,
    litter_is_sampleable,
)
from .events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayMoved,
    GlobeMotorFaultChanged,
    HopperDispensed,
    events_from_readings,
)
from .models import LitterRobot4State
from .protocol import ActivityMessage, StateMessage

__all__ = [
    "ACCEPTED_EVIDENCE",
    "EXCESS_WEIGHT_AFTER",
    "Capability",
    "CapabilitySighted",
    "DerivedState",
    "Effect",
    "Evidence",
    "FirmwareChanged",
    "HopperFillChanged",
    "LearnedChanged",
    "Update",
    "apply_message",
    "excess_weight",
    "globe_motor_faulted",
    "hopper_empty",
    "hopper_level_percent",
    "litter_scale",
    "sighting_stands",
]

# Two dispense reports closer together than this are the same event redelivered;
# real dispenses are a cycle or more apart.
DISPENSE_DEDUPE = timedelta(seconds=60)
# State documents arrive on a multi-minute cadence, so anything closer than this
# is a redelivery rather than an independent observation.
STATE_DEDUPE = timedelta(seconds=30)
# How long after the beam clears a visit close still counts as that visit's. The
# observed gap was one second; this is loose enough for a slow publish and far
# tighter than the minutes between handling the robot and its Reset.
VISIT_CLOSE_GRACE = timedelta(seconds=90)
# Whisker's own threshold for "excess weight detected".
EXCESS_WEIGHT_AFTER = timedelta(minutes=30)


class Capability(StrEnum):
    """A fact that only some robots ever report, and must be proven per robot.

    A consumer that surfaces one of these before the robot has produced it shows
    a value that may never arrive: no hopperless robot dispenses, ESP 1.1.75
    never emits a visit duration, and one live robot has never reported a cat
    weight. Each is withheld until this robot proves it owns the fact.
    """

    HOPPER = "hopper"
    VISIT_DURATION = "visit_duration"
    DRAWER = "drawer"
    PET_WEIGHT = "pet_weight"
    CAT_VISIT = "cat_visit"


class Evidence(StrEnum):
    """What proved a capability, stored alongside the sighting.

    The standard of proof has changed twice — the dispense burst was accepted
    then narrowed, and the ``0x57`` link report was retired outright — and a
    sighting that records only *that* it happened cannot say whether the next
    change invalidates it. Recording the evidence means a rule change retires
    exactly the sightings it disagrees with, and leaves the rest alone.
    """

    DISPENSE = "dispense"
    VISIT_DURATION = "visit_duration"
    CAT_WEIGHT = "cat_weight"
    DRAWER_MOVED = "drawer_moved"
    OCCUPANCY = "occupancy"
    #: A value the capability's own reporting still held from a previous run,
    #: recovered by a consumer rather than watched live.
    RESTORED = "restored"
    #: Proven by a build that did not record what proved it.
    LEGACY = "legacy"


#: What still counts as proof of each capability. Retiring a kind from a set
#: here is how a change to the standard of proof invalidates exactly the
#: sightings it disagrees with — which is the reason each one records its
#: evidence at all. LEGACY is accepted because the builds that recorded nothing
#: had their sightings re-derived by the one-off sweeps that retired the
#: standards already known to be wrong; a future change that doubts them again
#: drops LEGACY from the set it concerns.
ACCEPTED_EVIDENCE: dict[Capability, frozenset[Evidence]] = {
    Capability.HOPPER: frozenset({Evidence.DISPENSE, Evidence.RESTORED, Evidence.LEGACY}),
    # Deliberately NOT restorable: earlier builds recorded this from evidence
    # since proven wrong, so a restored duration is itself the suspect thing.
    Capability.VISIT_DURATION: frozenset({Evidence.VISIT_DURATION, Evidence.LEGACY}),
    Capability.DRAWER: frozenset({Evidence.DRAWER_MOVED, Evidence.RESTORED, Evidence.LEGACY}),
    Capability.PET_WEIGHT: frozenset({Evidence.CAT_WEIGHT, Evidence.RESTORED, Evidence.LEGACY}),
    Capability.CAT_VISIT: frozenset(
        {
            Evidence.CAT_WEIGHT,
            Evidence.VISIT_DURATION,
            Evidence.OCCUPANCY,
            Evidence.RESTORED,
            Evidence.LEGACY,
        }
    ),
}


def sighting_stands(capability: Capability, evidence: object) -> bool:
    """Whether a recorded sighting survives the current standard of proof.

    Anything this build does not recognize is trusted rather than re-examined:
    an unknown kind was written by a NEWER build, and a downgrade must not throw
    away what a later, stricter standard accepted — the mistake a global
    "re-check everything" counter made every time it moved.
    """
    if not isinstance(evidence, str):
        return bool(evidence)  # the bare flag of a build that recorded no kind
    try:
        kind = Evidence(evidence)
    except ValueError:
        return True
    return kind in ACCEPTED_EVIDENCE[capability]


@dataclass(frozen=True, slots=True)
class LearnedChanged:
    """The learned scales moved and should be written to durable storage."""


@dataclass(frozen=True, slots=True)
class HopperFillChanged:
    """A fresh dispense reported a new fill gauge."""

    value: int


@dataclass(frozen=True, slots=True)
class CapabilitySighted:
    """This robot proved, for the first time, that it owns ``capability``."""

    capability: Capability
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class FirmwareChanged:
    """The robot is running a different build than the one last seen."""

    version: str


Effect: TypeAlias = LearnedChanged | HopperFillChanged | CapabilitySighted | FirmwareChanged


@dataclass
class DerivedState:
    """Everything derived from the stream so far, and nothing from one message.

    Serializable in full (:meth:`as_dict`), so a consumer can carry it across a
    restart or a reload instead of rebuilding it field by field.
    """

    cat_weight_lb: float | None = None
    last_cat_visit: datetime | None = None
    last_visit_duration_s: int | None = None
    # `on` once the robot has actually delivered litter, and never `off`: there
    # is no disconnect signal, and a missing hopper is indistinguishable from a
    # well-fed one because dispensing is demand-driven.
    hopper_connected: bool | None = None
    last_hopper_dispensed: datetime | None = None
    hopper_fill_raw: int | None = None
    drawer_last_moved: datetime | None = None
    # From the ACTIVITY stream, not the state document: one robot held a live
    # globe-motor fault for 50 minutes while globeMotorFaultStatus read 0 in
    # every state document it published.
    globe_motor_fault: int | None = None
    # When the scale entered its current continuous loaded run, or None.
    scale_loaded_since: datetime | None = None
    # Verdicts a consumer carried across a restart, because the evidence behind
    # them cannot be: the fault stream speaks only on edges, and the start of a
    # loaded run lives in memory. Both are retired below by positive evidence
    # rather than by time, since a restart inside either condition is exactly
    # when they matter.
    globe_fault_restored: bool | None = None
    excess_weight_restored: bool | None = None
    # The clean-cycle odometer as last seen, so a restored fault can be retired
    # by a cycle that completes without raising one.
    cycles_seen: int | None = None
    # When the time-of-flight beam was last broken. The visit gate reads this
    # rather than a sticky flag: an arm crossing the beam without loading the
    # scale would otherwise arm the gate indefinitely, and the next Reset
    # phantom would sail through it.
    beam_broken_at: datetime | None = None
    # Occupancy as of the last state document, so the arrival edge is visible.
    occupied: bool | None = None
    # The build last seen, so an OTA that lands while a consumer stays running
    # can be reported rather than waiting for the next reload.
    esp_firmware: str | None = None
    learned_litter: Learned = field(default_factory=Learned)
    learned_hopper: Learned = field(default_factory=Learned)
    # When each stream was last sampled into the learned scales. Both
    # subscriptions are QoS 1, so a redelivery arrives seconds after the reading
    # it duplicates, and counting it as an independent observation would let one
    # reading corroborate itself.
    last_hopper_sample_at: datetime | None = None
    last_litter_sample_at: datetime | None = None
    #: Capability -> the evidence that proved it.
    sightings: dict[Capability, Evidence] = field(default_factory=dict)

    def copy(self) -> DerivedState:
        """A deep-enough copy that folding a message cannot touch the original."""
        return replace(
            self,
            learned_litter=self.learned_litter.copy(),
            learned_hopper=self.learned_hopper.copy(),
            sightings=dict(self.sightings),
        )

    def sighted(self, capability: Capability) -> bool:
        return capability in self.sightings

    @classmethod
    def from_dict(cls, raw: Any) -> DerivedState:
        """Rebuild from :meth:`as_dict`, tolerating anything else.

        Defensive on purpose: this reads back whatever a consumer stored, which
        may have been written by an older version or hand-edited.
        """
        if not isinstance(raw, dict):
            return cls()
        sightings: dict[Capability, Evidence] = {}
        stored = raw.get("sightings")
        if isinstance(stored, dict):
            for name, evidence in stored.items():
                try:
                    sightings[Capability(name)] = Evidence(evidence)
                except ValueError:
                    continue
        return cls(
            cat_weight_lb=_as_float(raw.get("cat_weight_lb")),
            last_cat_visit=_as_datetime(raw.get("last_cat_visit")),
            last_visit_duration_s=_as_int(raw.get("last_visit_duration_s")),
            hopper_connected=_as_bool(raw.get("hopper_connected")),
            last_hopper_dispensed=_as_datetime(raw.get("last_hopper_dispensed")),
            hopper_fill_raw=_as_int(raw.get("hopper_fill_raw")),
            drawer_last_moved=_as_datetime(raw.get("drawer_last_moved")),
            globe_motor_fault=_as_int(raw.get("globe_motor_fault")),
            scale_loaded_since=_as_datetime(raw.get("scale_loaded_since")),
            globe_fault_restored=_as_bool(raw.get("globe_fault_restored")),
            excess_weight_restored=_as_bool(raw.get("excess_weight_restored")),
            cycles_seen=_as_int(raw.get("cycles_seen")),
            beam_broken_at=_as_datetime(raw.get("beam_broken_at")),
            occupied=_as_bool(raw.get("occupied")),
            esp_firmware=_as_str(raw.get("esp_firmware")),
            learned_litter=Learned.from_dict(raw.get("learned_litter")),
            learned_hopper=Learned.from_dict(raw.get("learned_hopper")),
            last_hopper_sample_at=_as_datetime(raw.get("last_hopper_sample_at")),
            last_litter_sample_at=_as_datetime(raw.get("last_litter_sample_at")),
            sightings=sightings,
        )

    def as_dict(self) -> dict[str, Any]:
        """A JSON-round-trippable snapshot of everything derived so far."""
        return {
            "cat_weight_lb": self.cat_weight_lb,
            "last_cat_visit": _iso(self.last_cat_visit),
            "last_visit_duration_s": self.last_visit_duration_s,
            "hopper_connected": self.hopper_connected,
            "last_hopper_dispensed": _iso(self.last_hopper_dispensed),
            "hopper_fill_raw": self.hopper_fill_raw,
            "drawer_last_moved": _iso(self.drawer_last_moved),
            "globe_motor_fault": self.globe_motor_fault,
            "scale_loaded_since": _iso(self.scale_loaded_since),
            "globe_fault_restored": self.globe_fault_restored,
            "excess_weight_restored": self.excess_weight_restored,
            "cycles_seen": self.cycles_seen,
            "beam_broken_at": _iso(self.beam_broken_at),
            "occupied": self.occupied,
            "esp_firmware": self.esp_firmware,
            "learned_litter": self.learned_litter.as_dict(),
            "learned_hopper": self.learned_hopper.as_dict(),
            "last_hopper_sample_at": _iso(self.last_hopper_sample_at),
            "last_litter_sample_at": _iso(self.last_litter_sample_at),
            "sightings": {str(k): str(v) for k, v in self.sightings.items()},
        }


@dataclass(frozen=True, slots=True)
class Update:
    """The result of folding one message in."""

    state: DerivedState
    #: Whether anything a consumer displays moved. A state document always
    #: carries fresh registers, so it is always true there; an activity message
    #: is mostly telemetry nobody surfaces.
    changed: bool = False
    effects: tuple[Effect, ...] = ()


def apply_message(
    state: DerivedState, message: StateMessage | ActivityMessage, now: datetime
) -> Update:
    """Fold one inbound message into the derived state."""
    working = state.copy()
    if isinstance(message, StateMessage):
        return _apply_state(working, message.state, now)
    return _apply_activity(working, message, now)


def _apply_state(state: DerivedState, robot: LitterRobot4State, now: datetime) -> Update:
    effects: list[Effect] = []
    # Visits are stamped from the occupancy transition too: some robots never
    # emit a weight or duration event, and their visits are real anyway.
    # cat_detected is bit 0 — bit-1-only runs last hours with an empty globe on
    # hopper robots and are not visits. False -> True only, since a first
    # document arriving mid-visit proves presence, not an arrival.
    previous_occupancy = state.occupied
    occupancy = robot.cat_detected
    if occupancy:
        state.beam_broken_at = now
    # The robot raises "excess weight detected" once the scale has read loaded
    # for over 30 minutes, and shows it on the panel as a partial yellow flash.
    # Nothing in the state document says so, but catDetect bit 1 is the input,
    # so the condition is derivable.
    if robot.scale_loaded:
        if state.scale_loaded_since is None:
            state.scale_loaded_since = now
    elif robot.scale_loaded is False:
        state.scale_loaded_since = None
        # A positive "the pan is clear" retires the carried verdict for good.
        # Left standing it would fire a false alarm at second zero of every
        # later loaded run: the latch exists only to bridge a restart that
        # landed mid-condition, and the first clear snapshot ends that.
        state.excess_weight_restored = None
    # A restored fault with no live edge otherwise has no way to ever turn off:
    # the state field's 0 is distrusted by design, so if the clear edge fired
    # while the consumer was down, the latch would re-restore itself forever. A
    # completed clean cycle is the escape — a fault DURING a cycle raises its
    # own edge, which outranks the latch anyway, so the odometer advancing
    # without one is positive evidence the globe turns.
    if robot.odometer_clean_cycles is not None:
        if (
            state.globe_fault_restored
            and state.globe_motor_fault is None
            and state.cycles_seen is not None
            and robot.odometer_clean_cycles > state.cycles_seen
        ):
            state.globe_fault_restored = False
        state.cycles_seen = robot.odometer_clean_cycles
    if previous_occupancy is False and occupancy is True:
        state.last_cat_visit = now
        effects += _sight(state, Capability.CAT_VISIT, Evidence.OCCUPANCY)
    # Reported only against a build already seen: the first document of a
    # session says what the robot runs, not that it changed.
    if (
        robot.esp_firmware is not None
        and state.esp_firmware is not None
        and robot.esp_firmware != state.esp_firmware
    ):
        effects.append(FirmwareChanged(robot.esp_firmware))
    if robot.esp_firmware is not None:
        state.esp_firmware = robot.esp_firmware
    state.occupied = occupancy
    effects += _learn_litter(state, robot, now)
    return Update(state=state, changed=True, effects=tuple(effects))


def _apply_activity(state: DerivedState, message: ActivityMessage, now: datetime) -> Update:
    effects: list[Effect] = []
    changed = False
    events = events_from_readings(message.readings)
    # A real dispense is a burst of 2-3 phase-tagged codes in one message. A
    # type-1 READ of 0x0C decodes to a single HopperDispensed too, and taking
    # that as proof would let one diagnostic read grow four hopper entities on
    # a robot that has none.
    dispensed_here = sum(isinstance(e, HopperDispensed) for e in events) > 1
    for event in events:
        if isinstance(event, CatWeightMeasured):
            state.cat_weight_lb = event.weight_lb
            state.last_cat_visit = now
            effects += _sight(state, Capability.PET_WEIGHT, Evidence.CAT_WEIGHT)
            effects += _sight(state, Capability.CAT_VISIT, Evidence.CAT_WEIGHT)
            changed = True
        elif isinstance(event, HopperDispensed):
            # A dispense is the only hopper evidence there is. 0x57 used to gate
            # this, on the belief that it reported the link; a narrated session
            # disproved that in both directions, and the gate then discarded
            # every fill sample on a robot that dispenses happily but rarely
            # emits 0x57.
            if not dispensed_here:
                continue
            state.last_hopper_dispensed = now
            state.hopper_connected = True  # something delivered litter
            if event.phase == lr4.HOPPER_DISPENSE_FILL_PHASE:
                if event.value != state.hopper_fill_raw:
                    state.hopper_fill_raw = event.value
                    effects.append(HopperFillChanged(event.value))
                effects += _learn_hopper(state, event.value, now)
            effects += _sight(state, Capability.HOPPER, Evidence.DISPENSE)
            changed = True
        elif isinstance(event, CatVisitEnded):
            # A visit needs a BODY, not just load on the scale. Handling the
            # robot raises 0xBC exactly like a cat does — a Reset press closed
            # one at 235 s and another at 172 s, both under the 300 s cap, and
            # both were published as genuine multi-minute cat visits. Bit 0 (the
            # time-of-flight sight line) is what a cat sets and a hand on the
            # bonnet does not, so it is the discriminator.
            if not _beam_seen_recently(state, now):
                continue
            state.beam_broken_at = None
            # The duration closes a visit even when it was too short for a
            # weight event, so it also stamps the visit time.
            state.last_visit_duration_s = event.duration_s
            state.last_cat_visit = now
            effects += _sight(state, Capability.VISIT_DURATION, Evidence.VISIT_DURATION)
            effects += _sight(state, Capability.CAT_VISIT, Evidence.VISIT_DURATION)
            changed = True
        elif isinstance(event, GlobeMotorFaultChanged):
            if event.code != state.globe_motor_fault:
                state.globe_motor_fault = event.code
                changed = True
        elif isinstance(event, DrawerBayMoved):
            state.drawer_last_moved = now
            effects += _sight(state, Capability.DRAWER, Evidence.DRAWER_MOVED)
            changed = True
    return Update(state=state, changed=changed, effects=tuple(effects))


def _sight(
    state: DerivedState, capability: Capability, evidence: Evidence
) -> list[Effect]:
    """Record a first sighting, or nothing at all if it was already proven."""
    if state.sighted(capability):
        return []
    state.sightings[capability] = evidence
    return [CapabilitySighted(capability, evidence)]


def _beam_seen_recently(state: DerivedState, now: datetime) -> bool:
    """Whether a body broke the beam recently enough to own a visit close.

    The close trails the departure: in a narrated visit ``catDetect`` fell to 0
    one second before ``0xBC`` arrived, so the gate cannot require the beam to
    still be broken. It also cannot latch forever, or an arm reaching in would
    license a Reset phantom minutes later.
    """
    if state.beam_broken_at is None:
        return False
    return (now - state.beam_broken_at) <= VISIT_CLOSE_GRACE


def _learn_litter(state: DerivedState, robot: LitterRobot4State, now: datetime) -> list[Effect]:
    """Fold this report into the learned litter scale.

    Guarded three ways: only a settled robot is sampled, values outside the
    physically plausible band are discarded, and a new extreme has to be
    corroborated before it becomes an anchor. See calibration.py.
    """
    if state.last_litter_sample_at is not None and now - state.last_litter_sample_at < STATE_DEDUPE:
        return []
    state.last_litter_sample_at = now
    if not litter_is_sampleable(robot):
        return []
    assert robot.litter_level_mm is not None
    moved = state.learned_litter.observe(
        robot.litter_level_mm,
        bounds=LITTER_PLAUSIBLE_MM,
        corroboration=LITTER_CORROBORATION_MM,
        max_span=LITTER_MAX_SPAN_MM,
        # Dense enough for the Hampel gate: an in-band anomaly (a paw a few cm
        # above the bed) reads like an overfull globe, and two in one day would
        # corrupt the anchor as an ordinary pair.
        gate=True,
    )
    # Only when something actually changed. A new extreme is rare, so this is
    # not the per-state-document write it might look like.
    return [LearnedChanged()] if moved else []


def _learn_hopper(state: DerivedState, raw: int, now: datetime) -> list[Effect]:
    """Fold one FRESH dispense gauge reading into the hopper scale.

    Deliberately driven by the dispense event rather than by state documents:
    the last reading is retained between dispenses, so sampling it on every
    heartbeat would let a single bad value corroborate itself within seconds and
    become an anchor.

    Redelivery is a TIME property: separate dispenses are cycles apart,
    redeliveries arrive within seconds. Deduplicating by value instead would
    discard the repeated floor readings that are the entire evidence for
    "empty".
    """
    if (
        state.last_hopper_sample_at is not None
        and now - state.last_hopper_sample_at < DISPENSE_DEDUPE
    ):
        return []
    state.last_hopper_sample_at = now
    moved = state.learned_hopper.observe(
        raw,
        bounds=HOPPER_PLAUSIBLE,
        corroboration=HOPPER_CORROBORATION,
        count_hits=True,
    )
    return [LearnedChanged()] if moved else []


# --- the read model: what the derived state means ------------------------------
def litter_scale(
    state: DerivedState, *, full_mm: int | None = None, empty_mm: int | None = None
) -> tuple[int | None, int | None]:
    """The (full, empty) pair the litter percentage should be read against.

    The user's own measurements win outright. Failing those, the learned
    minimum is the fullest reading SEEN, a decent estimate of a full fill
    because that is what people fill to, so it stands in for the manual
    reference and anchors 90%. The learned maximum is NOT evidence the globe was
    ever emptied, so it is never used as the zero end: that would report "empty"
    at whatever level this robot happens to sit lowest, which for most robots is
    an ordinary day.
    """
    if full_mm is not None:
        return full_mm, empty_mm
    return state.learned_litter.low, None


def hopper_level_percent(state: DerivedState) -> int | None:
    """The hopper gauge as a percentage, or None until the scale is known."""
    if state.hopper_fill_raw is None:
        return None
    return hopper_percent(state.hopper_fill_raw, state.learned_hopper)


def hopper_empty(state: DerivedState) -> bool | None:
    """Whether the gauge sits at this unit's confirmed empty floor."""
    if state.hopper_fill_raw is None:
        return None
    return hopper_is_empty(state.hopper_fill_raw, state.learned_hopper)


def globe_motor_faulted(state: DerivedState, robot: LitterRobot4State) -> bool | None:
    """Globe-motor fault, from the activity stream OR the state document.

    It cannot read the state document alone. One robot raised a fault on the
    activity stream, held it for 50 minutes and cleared it, while
    ``globeMotorFaultStatus`` read 0 in every one of the 1198 state documents it
    published across that capture — including six sampled during the fault
    itself. A consumer watching the field stayed clear throughout a real fault.

    Either source raising a fault is a fault; the field is kept because it is
    the only source on firmware that does populate it.
    """
    from_field = robot.globe_motor_fault
    if state.globe_motor_fault is not None:
        return bool(state.globe_motor_fault) or bool(from_field)
    # No edge seen this session. The field reading 0 is NOT evidence of no
    # fault — that is the whole finding — so a carried verdict outranks it.
    if state.globe_fault_restored is not None:
        return state.globe_fault_restored or bool(from_field)
    return None if from_field is None else bool(from_field)


def excess_weight(state: DerivedState, robot: LitterRobot4State, now: datetime) -> bool | None:
    """Whether something has been sitting on the scale past Whisker's threshold.

    The robot raises this itself and shows it on the panel as a blue bar with a
    partial yellow flash, but says nothing about it in the state document. Its
    own documentation defines the condition as the scale having read loaded for
    over 30 minutes, and catDetect bit 1 is that reading, so the condition is
    derivable even though the flag is not published.

    It matters because the robot will not cycle while it believes it is
    occupied. One unit here held bit 1 for 2 h 09 m after a bonnet was reseated
    slightly off, with its clean-cycle countdown stuck the whole time.

    A carried verdict bridges a restart mid-condition, where the run start is
    lost: still loaded and previously yes means the condition never cleared,
    this process just forgot when it started.
    """
    if state.scale_loaded_since is None:
        # Only a positive "the pan is clear" is an off; an absent bit is unknown.
        return False if robot.scale_loaded is False else None
    if (now - state.scale_loaded_since) >= EXCESS_WEIGHT_AFTER:
        return True
    return bool(state.excess_weight_restored)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
