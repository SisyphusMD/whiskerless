"""Learning each robot's own scale from what it reports over time.

Two of the numbers consumers surface have no absolute meaning:

* **litter level** is a ToF *distance*, and the cloud converts it against a
  per-robot reference that the local state document does not contain.
* **hopper fill** is a raw gauge whose floor and ceiling differ per unit
  (61 and 76 on one robot against 66-70 and 84 on another).

Rather than demand the user calibrate both by hand, watch what the robot
actually reports and learn from it. An explicit calibration always wins; this
only fills in what the user has not measured themselves.

**What an observed extreme does and does not prove.** Seeing the litter sit at
440 mm once does not mean the globe was full, and seeing 465 mm does not mean it
was empty; they are simply the ends of the range this robot has happened to
occupy. Treating them as 100% and 0% would report "empty" at a perfectly normal
level. So the learned minimum is used the way the manual reference is used, as
an estimate of "about a full fill" anchored to 90%, and no claim is made about
the empty end at all. The hopper is stricter still: its floor is only believed
once the gauge has flatlined there across several separate dispenses, which is
the signature of a genuinely empty hopper rather than a deep one.

The whole risk here is learning a wrong extreme, because a bad anchor is
permanent, silent, and skews every later reading. Four guards, in order of how
much work they do:

1. **Only sample a settled robot.** A cat on the scale, a running cycle, or any
   status other than ready disqualifies the reading outright.
2. **Reject the physically impossible.** The globe holds roughly two inches of
   litter, so the bed can only occupy a narrow band of distances, and it can
   only MOVE by about that much between brim-full and bare. A cat standing in
   it is several inches tall, which puts its back far outside that band:
   ``litterLevel`` read 253 mm during a captured visit against a 428-462 mm
   bed. The rotating globe mid-cycle reads 540-575 mm. Both are excluded by
   simple physics, no statistics required.
3. **Quarantine the statistically implausible** (dense signals only). A Hampel
   identifier over a short rolling window catches what physics cannot: an
   IN-band anomaly, like a paw or a toy a few centimetres above the bed,
   reads like an overfull globe. Consecutive agreeing rejections still let a
   genuine regime change (a refill) through — the world outvotes the window.
   The hopper's per-dispense trickle is far below what any robust scale
   estimator supports, so it relies on guard 4 and flatline runs instead.
4. **Require corroboration.** A new extreme is held as a candidate and only
   becomes the anchor when a second, independent reading lands near it. One
   spurious sample can never move the scale on its own. A cat rarely holds the
   same pose twice within a few millimetres, whereas a litter bed sits still,
   which is what makes this effective exactly where the other guards run out.

The hopper floor is special: it is learned from **flatline runs**, in both
directions. Every real dispense removes litter, so consecutive dispense
readings that do not fall mean nothing is being delivered — empty at that
level, wherever it sits, which finds a floor that moved UP (litter change,
auger residue) as readily as one below the record. A ceiling-distance guard
keeps maintained-top flatlines (an owner topping up after every dispense) from
ever reading as a floor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import LitterRobot4State

# Plausible litter-surface distances. The bed sits at 428-462 mm across both
# robots we have data from, and the globe only holds about two inches, so the
# surface cannot wander far from there. Wide enough for an overfilled globe and
# a bare one; far from a cat's back (253 mm captured) or the rotating globe
# mid-cycle (540-575 mm captured).
LITTER_PLAUSIBLE_MM = (400, 530)

# Brim-full to bare cannot span more than the globe's litter depth, which is a
# couple of inches. Set generously above that estimate on purpose: this is a
# backstop for the absurd, not a precise physical claim, and the observed band
# above is the guard doing the real work.
LITTER_MAX_SPAN_MM = 100

# Hopper gauge readings seen across two robots span 61-92. Wide bounds, because
# corroboration is what actually protects this one.
HOPPER_PLAUSIBLE = (10, 300)

# How close a second reading must land for a candidate extreme to be trusted.
LITTER_CORROBORATION_MM = 6
HOPPER_CORROBORATION = 4

# The gauge band observed across units so far: floors 61-70, maintained tops
# 84-92. A provisional display percentage maps over this typical band until the
# robot's own floor is learned; it never feeds the learned anchors.
HOPPER_FILL_TYPICAL_RANGE = (66, 90)

# Refuse to derive a percentage from a scale too narrow to be real, which would
# turn ordinary noise into large swings.
LITTER_MIN_SPAN_MM = 25
HOPPER_MIN_SPAN = 8

# Separate dispenses that must flatline together before that level is believed
# to be the floor: consecutive dispenses each remove litter, so an unchanged
# gauge across several of them means nothing is being delivered.
HOPPER_EMPTY_CONFIRMATIONS = 3

# Hampel-identifier gate, for DENSE signals only. The litter stream delivers
# dozens of sampleable readings a day, enough for a short rolling window; the
# hopper's per-dispense trickle (three to eight points) is below what any
# robust scale estimator can support, so it uses run repetition instead.
_WINDOW = 15
_WINDOW_WARMUP = 5
# 1.4826 scales a MAD to a standard deviation under normality; 3.5 is the
# customary identifier threshold. The scale floor matters more than either: a
# litter bed legitimately flatlines, MAD collapses to zero there, and without a
# floor every small real move would be flagged as an outlier.
_MAD_TO_SIGMA = 1.4826
_SCALE_FLOOR = 2.0
_HAMPEL_THRESHOLD = 3.5
# Plain Hampel deadlocks on a regime change: after a refill moves the bed 20 mm
# in one step, every new reading is "an outlier" against the stale window
# forever. Consecutive rejections that AGREE with each other are the world
# changing, not the sensor lying, and the world wins.
_REGIME_REJECTIONS = 3
# A run tolerates this much downward wobble before it stops being a flatline.
# The captured drain arc falls ~2 gauge units per delivering dispense, while an
# empty hopper's flatline wobbles UPWARD (66-70); the fall direction is what
# distinguishes litter flowing from litter absent.
_RUN_FALL_TOLERANCE = 1


@dataclass
class Learned:
    """Observed extremes for one measurement, plus unconfirmed candidates."""

    low: int | None = None
    high: int | None = None
    low_candidate: int | None = None
    high_candidate: int | None = None
    # How many flatlined readings support the low anchor. A gauge that keeps
    # bottoming out at the same value is at its floor; one that touched it
    # once may simply have been low that day.
    low_hits: int = 0
    # The flatline run in progress for sparse signals: consecutive readings
    # within the corroboration band of the first. Persisted — at one dispense a
    # day, losing two of three confirmations to a restart could cost a week.
    run_value: int | None = None
    run_length: int = 0
    # Whether this run was entered by a FALL. A maintained level is flat too,
    # but it is topped up from below rather than declined into, and only a
    # declined-into flatline is evidence of empty.
    run_fell: bool = False
    # Session-only Hampel state for dense signals, deliberately NOT persisted:
    # the window rebuilds within minutes from the litter stream, and writing
    # the options on every accepted state document would be a write storm.
    window: list[int] = field(default_factory=list)
    rejects: list[int] = field(default_factory=list)
    fresh_regime: bool = field(default=False)

    @classmethod
    def from_dict(cls, raw: Any) -> Learned:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            low=_as_int(raw.get("low")),
            high=_as_int(raw.get("high")),
            low_candidate=_as_int(raw.get("low_candidate")),
            high_candidate=_as_int(raw.get("high_candidate")),
            low_hits=_as_int(raw.get("low_hits")) or 0,
            run_value=_as_int(raw.get("run_value")),
            run_length=_as_int(raw.get("run_length")) or 0,
            run_fell=bool(raw.get("run_fell")),
        )

    def as_dict(self) -> dict[str, int | None]:
        data = asdict(self)
        del data["window"], data["rejects"], data["fresh_regime"]
        return data

    def span_ok(self, minimum: int) -> bool:
        return self.low is not None and self.high is not None and self.high - self.low >= minimum

    def observe(
        self,
        value: int,
        *,
        bounds: tuple[int, int],
        corroboration: int,
        max_span: int | None = None,
        count_hits: bool = False,
        gate: bool = False,
    ) -> bool:
        """Fold one reading in. Returns whether anything persisted changed.

        Candidates count as a change so callers can persist them: a dispense
        arrives every few cycles at best, and discarding an unconfirmed
        candidate on every restart could mean never accumulating the second
        reading that confirms it.

        A value beyond a current anchor does not become the anchor; it becomes
        a candidate, and is promoted only when a later reading lands within
        ``corroboration`` of it. That is what stops a single bad sample from
        permanently redefining the scale.

        ``gate`` (dense signals only) puts a Hampel identifier in front: the
        physics band cannot catch an IN-band anomaly — a paw or a toy a few cm
        above the bed reads like an overfull globe, and two such readings on
        the same day would corrupt the anchor as an ordinary corroborated
        pair. The gate quarantines anything far from the rolling median, while
        consecutive agreeing rejections still let a genuine regime change
        (a refill) through.

        ``count_hits`` (sparse signals) learns the floor from flatline runs —
        in both directions, see :meth:`_observe_run`.
        """
        if not bounds[0] <= value <= bounds[1]:
            return False
        if max_span is not None:
            other = self.high if value < (self.low or value) else self.low
            if other is not None and abs(value - other) > max_span:
                # Accepting this would imply the bed moved further than the
                # globe can physically hold.
                return False
        if gate and not self._passes_gate(value, corroboration):
            return False

        before = self._anchors()
        if count_hits:
            self._observe_run(value, corroboration)
            self._observe_high(value, corroboration)
        elif self.low is None or value < self.low:
            if self.low_candidate is not None and abs(value - self.low_candidate) <= corroboration:
                self.low = max(value, self.low_candidate)
                self.low_candidate = None
                self.low_hits = 0
            else:
                self.low_candidate = value
        else:
            self._observe_high(value, corroboration)
        return before != self._anchors()

    def _anchors(self) -> tuple[int | None, ...]:
        return (
            self.low,
            self.high,
            self.low_candidate,
            self.high_candidate,
            self.low_hits,
            self.run_value,
            self.run_length,
            int(self.run_fell),
        )

    def _observe_high(self, value: int, corroboration: int) -> None:
        if self.high is None or value > self.high:
            if self.high_candidate is not None and abs(value - self.high_candidate) <= corroboration:
                self.high = min(value, self.high_candidate)
                self.high_candidate = None
            else:
                self.high_candidate = value

    def _observe_run(self, value: int, corroboration: int) -> None:
        """Track the flatline run, and let a confirmed one place the floor.

        Every real dispense removes litter, so the gauge falls a little each
        time litter actually flows; readings that flatline together mean
        nothing is being delivered — the hopper is empty AT that level,
        wherever it sits. That finds a floor ABOVE the recorded one (a litter
        change, auger residue) exactly as it finds one below.

        A DRAINING gauge is not a flatline: it falls a little per delivering
        dispense, and a loose membership band would let three drain steps
        confirm mid-drain. Any fall beyond the wobble tolerance breaks the run
        (the empty flatline wobbles upward, never down).

        Two guards keep a MAINTAINED level from ever reading as a floor: the
        run must have been entered by a fall (an owner topping up after every
        dispense re-enters from below), and it must sit well below the learned
        ceiling — which those same maintained-top readings teach first, as an
        ordinary corroborated pair. Until a ceiling exists, no run confirms
        anything. An owner who deliberately re-maintains at a sharply lower
        level can still fool this for a while; a later true drain re-anchors,
        and no signal available here can tell those apart sooner.

        The run length is capped at the confirmation count so a hopper left
        empty for a week of futile dispenses stops changing state — and stops
        rewriting the stored options — once the floor is settled.
        """
        if (
            self.run_value is not None
            and abs(value - self.run_value) <= corroboration
            and value >= self.run_value - _RUN_FALL_TOLERANCE
        ):
            self.run_length = min(self.run_length + 1, HOPPER_EMPTY_CONFIRMATIONS)
        else:
            # With no prior run (a record persisted before runs existed), the
            # stored floor is the reference — a first reading below it is the
            # decline it looks like, or a migrated record could never deepen.
            reference = self.run_value if self.run_value is not None else self.low
            self.run_fell = reference is not None and value < reference
            self.run_value = value
            self.run_length = 1
        if (
            self.run_length >= HOPPER_EMPTY_CONFIRMATIONS
            and self.run_fell
            and self.high is not None
            and self.run_value <= self.high - HOPPER_MIN_SPAN
        ):
            self.low = self.run_value
            self.low_hits = HOPPER_EMPTY_CONFIRMATIONS

    def _passes_gate(self, value: int, corroboration: int) -> bool:
        """Hampel identifier over a short rolling window of accepted readings.

        The scale floor keeps a legitimately flatlined window (MAD zero) from
        flagging every small real move; the agreeing-rejection streak keeps a
        regime change (a refill steps the bed 20+ mm at once) from deadlocking
        against a stale window forever, which is plain Hampel's known failure
        on non-stationary signals.
        """
        window = self.window
        outlier = False
        if len(window) >= _WINDOW_WARMUP:
            ordered = sorted(window)
            median = ordered[len(ordered) // 2]
            deviations = sorted(abs(v - median) for v in window)
            scale = max(deviations[len(deviations) // 2] * _MAD_TO_SIGMA, _SCALE_FLOOR)
            outlier = abs(value - median) > _HAMPEL_THRESHOLD * scale
        elif not self.fresh_regime and self.low is not None and self.high is not None:
            # The window is session-only, so every restart begins in warm-up —
            # exactly when a restored anchor is most exposed. Until the window
            # can vote, the persisted anchors say where the bed lives; a
            # regime flush suspends this, or the flushed readings would be
            # re-rejected against the anchors they just outvoted.
            margin = _HAMPEL_THRESHOLD * _SCALE_FLOOR
            outlier = not (self.low - margin <= value <= self.high + margin)
        if outlier:
            if self.rejects and abs(value - self.rejects[-1]) > corroboration:
                self.rejects.clear()
            self.rejects.append(value)
            if len(self.rejects) >= _REGIME_REJECTIONS:
                window[:] = self.rejects
                self.rejects.clear()
                self.fresh_regime = True
                return True
            return False
        window.append(value)
        del window[:-_WINDOW]
        self.rejects.clear()
        return True


def litter_is_sampleable(robot: LitterRobot4State) -> bool:
    """Whether this state document can be trusted to describe the litter bed.

    Guard 1. A cat on the scale reads its body rather than the litter, and a
    cycle points the sensors at the rotating globe. Anything but a settled,
    empty, idle robot is discarded before the value is even looked at.
    """
    return (
        robot.litter_level_mm is not None
        and not robot.is_cleaning
        and robot.cat_detected is False
        and robot.robot_status == "ready"
    )


def hopper_percent_provisional(raw: int) -> int:
    """A display-only estimate against the typical band, for an uncalibrated unit.

    Per-unit floors and ceilings vary enough that this can be off by tens of
    points; it exists so an uncalibrated hopper shows an estimate rather than
    unknown, and consumers should label it as such.
    """
    low, high = HOPPER_FILL_TYPICAL_RANGE
    return max(min(round((raw - low) / (high - low) * 100), 100), 0)


def hopper_is_empty(raw: int, learned: Learned) -> bool | None:
    """Whether the gauge sits at this unit's confirmed empty floor.

    ``None`` until the floor has been hit repeatedly — the same standard
    :func:`hopper_percent` holds itself to, and for the same reason: floors
    differ per unit, so a fixed threshold calls a low-reading hopper empty
    while litter still flows. A reading at or below the confirmed floor
    (within the corroboration band) is the flatline signature of a bare auger.
    """
    if learned.low is None or learned.low_hits < HOPPER_EMPTY_CONFIRMATIONS:
        return None
    return raw - learned.low <= HOPPER_CORROBORATION


def hopper_percent(raw: int, learned: Learned) -> int | None:
    """Convert the raw gauge to a percentage once the scale is genuinely known.

    Inverted against litter: a HIGHER gauge reading means more litter, so the
    learned low is empty and the learned high is full.

    Returns None until the floor has been hit repeatedly. An empty hopper
    flatlines at its floor while dispenses keep running and deliver nothing; a
    single low reading proves only that the hopper was low, and calling that 0%
    would report empty on a hopper that still has litter in it.
    """
    if not learned.span_ok(HOPPER_MIN_SPAN) or learned.low_hits < HOPPER_EMPTY_CONFIRMATIONS:
        return None
    assert learned.low is not None and learned.high is not None
    span = learned.high - learned.low
    return max(min(round((raw - learned.low) / span * 100), 100), 0)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
