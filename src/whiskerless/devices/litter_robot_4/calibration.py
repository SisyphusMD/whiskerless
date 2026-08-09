"""Learning each robot's own scale from what it reports over time.

Two of this integration's numbers have no absolute meaning:

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
permanent, silent, and skews every later reading. Three guards, in order of how
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
3. **Require corroboration.** A new extreme is held as a candidate and only
   becomes the anchor when a second, independent reading lands near it. One
   spurious sample can never move the scale on its own. A cat rarely holds the
   same pose twice within a few millimetres, whereas a litter bed sits still,
   which is what makes this effective exactly where guard 2 runs out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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

# Refuse to derive a percentage from a scale too narrow to be real, which would
# turn ordinary noise into large swings.
LITTER_MIN_SPAN_MM = 25
HOPPER_MIN_SPAN = 8

# Separate dispenses that must bottom out at the floor before it is believed to
# be empty rather than merely low.
HOPPER_EMPTY_CONFIRMATIONS = 3


@dataclass
class Learned:
    """Observed extremes for one measurement, plus unconfirmed candidates."""

    low: int | None = None
    high: int | None = None
    low_candidate: int | None = None
    high_candidate: int | None = None
    # How many separate readings have landed at the low anchor. A gauge that
    # keeps bottoming out at the same value is at its floor; one that touched it
    # once may simply have been low that day.
    low_hits: int = 0

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
        )

    def as_dict(self) -> dict[str, int | None]:
        return asdict(self)

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
    ) -> bool:
        """Fold one reading in. Returns whether anything changed.

        Candidates count as a change so callers can persist them: a dispense
        arrives every few cycles at best, and discarding an unconfirmed
        candidate on every restart could mean never accumulating the second
        reading that confirms it.

        A value beyond a current anchor does not become the anchor; it becomes a
        candidate, and is promoted only when a later reading lands within
        ``corroboration`` of it. That is what stops a single bad sample from
        permanently redefining the scale.
        """
        if not bounds[0] <= value <= bounds[1]:
            return False
        if max_span is not None:
            other = self.high if value < (self.low or value) else self.low
            if other is not None and abs(value - other) > max_span:
                # Accepting this would imply the bed moved further than the
                # globe can physically hold.
                return False

        before = (self.low, self.high, self.low_candidate, self.high_candidate, self.low_hits)
        # Hit counting exists only to confirm a hopper floor. Litter readings sit
        # near their low constantly, so counting them would rewrite the stored
        # options on every heartbeat for a number nothing reads. Capped once
        # confirmed, for the same reason.
        if (
            count_hits
            and self.low is not None
            # At or just above the floor only. A LOWER reading is evidence the
            # floor was wrong, not confirmation of it, and counting it would let
            # a single reading at a new low satisfy the requirement.
            and 0 <= value - self.low <= corroboration
            and self.low_hits < HOPPER_EMPTY_CONFIRMATIONS
        ):
            self.low_hits += 1
        if self.low is None or value < self.low:
            if self.low_candidate is not None and abs(value - self.low_candidate) <= corroboration:
                self.low = max(value, self.low_candidate)
                self.low_candidate = None
                self.low_hits = 2 if count_hits else 0
            else:
                self.low_candidate = value
        elif self.high is None or value > self.high:
            if self.high_candidate is not None and abs(value - self.high_candidate) <= corroboration:
                self.high = min(value, self.high_candidate)
                self.high_candidate = None
            else:
                self.high_candidate = value
        return before != (self.low, self.high, self.low_candidate, self.high_candidate, self.low_hits)


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
