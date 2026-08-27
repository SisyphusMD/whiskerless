"""Learning a robot's own scale, and refusing to learn the wrong one.

A bad anchor is permanent, silent, and skews every later reading, so these tests
are mostly about what must NOT be learned.
"""

from __future__ import annotations

import pytest

from whiskerless.devices.litter_robot_4 import LitterRobot4State
from whiskerless.devices.litter_robot_4.calibration import (
    HOPPER_CORROBORATION,
    HOPPER_EMPTY_CONFIRMATIONS,
    HOPPER_MIN_SPAN,
    HOPPER_PLAUSIBLE,
    LITTER_CORROBORATION_MM,
    LITTER_MAX_SPAN_MM,
    LITTER_PLAUSIBLE_MM,
    Learned,
    hopper_is_empty,
    hopper_percent,
    hopper_percent_provisional,
    litter_is_sampleable,
)
from whiskerless.devices.litter_robot_4.models import litter_level_percent_from_mm

IDLE = {"robotStatus": 4, "catDetect": 0, "litterLevel": 455}


def _litter(learned: Learned, *values: int) -> Learned:
    for value in values:
        learned.observe(
            value,
            bounds=LITTER_PLAUSIBLE_MM,
            corroboration=LITTER_CORROBORATION_MM,
            max_span=LITTER_MAX_SPAN_MM,
        )
    return learned


# --- guard 1: only a settled robot is sampled at all --------------------------


def test_a_cat_on_the_scale_is_not_sampleable() -> None:
    assert not litter_is_sampleable(LitterRobot4State.from_state_doc({**IDLE, "catDetect": 1}))


def test_the_hopper_correlated_bit_does_not_block_a_litter_sample() -> None:
    assert litter_is_sampleable(LitterRobot4State.from_state_doc({**IDLE, "catDetect": 2}))


def test_a_running_cycle_is_not_sampleable() -> None:
    # robotStatus 10 also suppresses litter_level_mm outright, so this is belt
    # and braces, which is the point.
    assert not litter_is_sampleable(LitterRobot4State.from_state_doc({**IDLE, "robotStatus": 10}))


def test_any_status_other_than_ready_is_not_sampleable() -> None:
    for status in (5, 6, 7, 25):
        doc = {**IDLE, "robotStatus": status}
        assert not litter_is_sampleable(LitterRobot4State.from_state_doc(doc)), status


def test_a_settled_robot_is_sampleable() -> None:
    assert litter_is_sampleable(LitterRobot4State.from_state_doc(IDLE))


# --- guard 2: the physically impossible is rejected ---------------------------


@pytest.mark.parametrize("mm", [253, 317, 380])
def test_a_cat_in_the_globe_is_rejected(mm: int) -> None:
    # litterLevel read 253 mm during a captured cat visit, against a 428-462 mm
    # bed: the animal's back sits inches above a surface that can only occupy a
    # narrow band, so this needs no statistics to reject.
    learned = _litter(Learned(low=430, high=470), mm, mm)
    assert learned.low == 430, "a cat must never become the fullest reading"


def test_a_reading_implying_an_impossible_depth_is_rejected() -> None:
    # In band, corroborated, and still refused: accepting it would mean the bed
    # moved further than two inches of litter can account for.
    learned = _litter(Learned(low=490, high=530), 405, 405)
    assert learned.low == 490


def test_the_rotating_globe_is_rejected() -> None:
    # 540-575 mm captured mid-cycle, the sensors seeing the globe not the bed.
    learned = _litter(Learned(low=430, high=470), 700, 700)
    assert learned.high == 470


# --- guard 3: one reading never moves the scale -------------------------------


def test_a_single_extreme_is_only_a_candidate() -> None:
    learned = _litter(Learned(low=430, high=470), 400)
    assert learned.low == 430
    assert learned.low_candidate == 400


def test_a_corroborated_extreme_is_promoted() -> None:
    learned = _litter(Learned(low=430, high=470), 400, 402)
    assert learned.low == 402, "the conservative end of the corroborated pair"


def test_a_lone_outlier_never_promotes() -> None:
    # One wild reading among ordinary ones leaves the anchors untouched.
    learned = _litter(Learned(low=430, high=470), 385, 450, 455, 452)
    assert learned.low == 430
    assert learned.high == 470


def test_a_repeated_reading_is_corroboration_even_if_not_consecutive() -> None:
    # Deliberate: the candidate persists, so evidence does not have to arrive
    # back to back. Litter settles at a level and stays there across reports.
    learned = _litter(Learned(low=430, high=470), 420, 450, 421)
    assert learned.low == 421


# --- the hopper scale ---------------------------------------------------------


def test_a_low_reading_alone_is_not_evidence_of_empty() -> None:
    # The floor has to be hit repeatedly. One low dispense means the hopper was
    # low, not that it was empty, and calling it 0% would be a lie told
    # confidently to someone who still has litter in there.
    assert hopper_percent(70, Learned(low=61, high=92, low_hits=1)) is None
    assert hopper_percent(70, Learned(low=61, high=92, low_hits=2)) is None
    assert hopper_percent(70, Learned(low=61, high=92, low_hits=3)) is not None


def test_hopper_percent_needs_a_believable_span() -> None:
    assert hopper_percent(70, Learned(low=68, high=70)) is None, "too narrow to be real"
    assert hopper_percent(70, Learned(low=None, high=90)) is None


def test_empty_is_unknowable_until_the_floor_is_confirmed() -> None:
    # Floors differ per unit — one robot's stocked readings sit below another's
    # empty flatline — so a fixed threshold would cry empty while litter flows.
    assert hopper_is_empty(61, Learned(low=None)) is None
    assert hopper_is_empty(61, Learned(low=61, high=92, low_hits=2)) is None


def test_empty_is_the_flatline_at_the_confirmed_floor() -> None:
    confirmed = Learned(low=66, high=90, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    assert hopper_is_empty(66, confirmed) is True
    assert hopper_is_empty(66 + HOPPER_CORROBORATION, confirmed) is True
    assert hopper_is_empty(64, confirmed) is True, "below the floor is emptier still"
    assert hopper_is_empty(66 + HOPPER_CORROBORATION + 1, confirmed) is False


def test_hopper_percent_maps_the_learned_range() -> None:
    # Our robot: 61 empty, 92 maintained. Higher gauge means MORE litter.
    learned = Learned(low=61, high=92, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    assert hopper_percent(61, learned) == 0
    assert hopper_percent(92, learned) == 100
    assert hopper_percent(76, learned) == 48


def test_hopper_percent_is_clamped_beyond_the_learned_range() -> None:
    learned = Learned(low=61, high=92, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    assert hopper_percent(120, learned) == 100
    assert hopper_percent(10, learned) == 0


def _hopper(learned: Learned, *values: int) -> None:
    for value in values:
        learned.observe(
            value,
            bounds=HOPPER_PLAUSIBLE,
            corroboration=HOPPER_CORROBORATION,
            count_hits=True,
        )


def test_hopper_learns_the_ceiling_from_pairs_and_the_floor_from_runs() -> None:
    learned = Learned()
    _hopper(learned, 92, 92, 76, 61, 61, 61)
    assert learned.high == 92
    assert learned.low == 61
    assert learned.low_hits == HOPPER_EMPTY_CONFIRMATIONS
    assert learned.span_ok(HOPPER_MIN_SPAN)


def test_the_floor_re_anchors_upward_on_a_higher_flatline() -> None:
    """A litter change or auger residue raises the true floor. A decline into
    repeated futile dispenses at the new level is the same evidence that found
    the old one — every real dispense drops the gauge; empty does not."""
    learned = Learned(low=61, high=92, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    _hopper(learned, 90, 74, 74, 75)  # a refill top, then the decline into 74
    assert learned.low == 74
    assert learned.low_hits == HOPPER_EMPTY_CONFIRMATIONS


def test_a_draining_gauge_is_not_a_flatline() -> None:
    """Drain steps stay inside a loose band of the run start; without the fall
    rule three of them would confirm a floor mid-drain, at 0%, while litter
    visibly flows."""
    learned = Learned(high=92)
    _hopper(learned, 78, 76, 74, 72, 70)
    assert learned.low is None


def test_a_flatline_entered_from_below_is_not_a_floor() -> None:
    """A maintained level is flat too — but it is topped up from below, not
    declined into, and only the declined-into kind is empty."""
    learned = Learned(low=61, high=92, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    _hopper(learned, 61, 84, 84, 84, 84)  # refill to a steady 84, kept there
    assert learned.low == 61, "the maintained level must not become the floor"


def test_a_maintained_top_flatline_is_not_a_floor() -> None:
    """An owner topping up after every dispense flatlines at the FULL level;
    reading that as empty is the inverse error. Those readings teach the
    ceiling instead, and a run only counts as a floor well below it."""
    learned = Learned()
    _hopper(learned, 89, 89, 89, 89, 89)
    assert learned.low is None
    assert learned.high == 89


def test_no_floor_is_confirmed_before_a_ceiling_exists() -> None:
    learned = Learned()
    _hopper(learned, 61, 61, 61, 61)
    assert learned.low is None


def test_a_broken_run_starts_over() -> None:
    """Two flatlined dispenses, a refill, then one more at the old value: the
    refill reading proves litter flowed, so the count must not resume at 3."""
    learned = Learned(high=92)
    _hopper(learned, 61, 61, 84, 61)
    assert learned.low is None
    assert learned.run_length == 1


def test_round_trips_through_storage() -> None:
    learned = Learned(
        low=61, high=92, low_candidate=58, run_value=61, run_length=2, run_fell=True
    )
    assert Learned.from_dict(learned.as_dict()) == learned
    assert Learned.from_dict(None) == Learned()
    assert Learned.from_dict({"low": "nonsense"}) == Learned()
    # A dict persisted before runs existed still loads.
    assert Learned.from_dict({"low": 61, "high": 92, "low_hits": 3}).low == 61


def test_the_hampel_window_is_never_persisted() -> None:
    """Session-only by design: it rebuilds in minutes from the litter stream,
    and persisting it would rewrite the options on every accepted reading."""
    learned = Learned()
    learned.observe(
        441, bounds=LITTER_PLAUSIBLE_MM, corroboration=LITTER_CORROBORATION_MM, gate=True
    )
    data = learned.as_dict()
    assert "window" not in data and "rejects" not in data


def _litter_gated(learned: Learned, *values: int) -> Learned:
    for value in values:
        learned.observe(
            value,
            bounds=LITTER_PLAUSIBLE_MM,
            corroboration=LITTER_CORROBORATION_MM,
            max_span=LITTER_MAX_SPAN_MM,
            gate=True,
        )
    return learned


def test_two_similar_in_band_anomalies_cannot_corrupt_the_anchor() -> None:
    """The hole the gate closes: a paw a few cm above the bed reads ~410 mm —
    inside the physical band — and two such readings in one day used to walk
    the full-anchor there as an ordinary corroborated pair."""
    learned = Learned()
    _litter_gated(learned, 441, 442, 441, 443, 442, 441)  # warm the window
    assert learned.low == 441
    _litter_gated(learned, 410)  # a paw
    _litter_gated(learned, 441)  # the bed again, breaking the rejection streak
    _litter_gated(learned, 412)  # another paw, hours later
    assert learned.low == 441, "quarantined anomalies must never pair up"
    assert learned.low_candidate is None


def test_a_real_refill_outvotes_the_window() -> None:
    """Plain Hampel deadlocks after a 20+ mm refill step — every new reading is
    an outlier against the stale window forever. Agreeing rejections are the
    world changing, not the sensor lying."""
    learned = Learned()
    _litter_gated(learned, 465, 465, 466, 465, 466, 465)
    _litter_gated(learned, 430, 431, 430, 431)
    assert learned.low == 431, "the refilled bed must become the new anchor"


def test_restored_anchors_gate_the_warmup_window() -> None:
    """The window is session-only, so every restart begins in warm-up — the
    exact moment a restored anchor used to be exposed to a pair of paws."""
    learned = Learned(low=440, high=465)
    _litter_gated(learned, 410, 412)
    assert learned.low == 440
    assert learned.low_candidate is None, "warm-up must not accept what the gate exists to stop"


def test_a_refill_during_warmup_still_outvotes_the_anchors() -> None:
    """Agreeing rejections rebuild the window; the anchor gate must then stand
    aside, or the flushed readings would be re-rejected against the very
    anchors they outvoted."""
    learned = Learned(low=460, high=470)
    _litter_gated(learned, 430, 431, 430, 431)
    assert learned.low == 431


def test_a_flatlined_window_still_accepts_small_real_moves() -> None:
    """MAD collapses to zero on a still bed; without the scale floor every
    2 mm settle would be flagged as an outlier."""
    learned = Learned()
    _litter_gated(learned, 443, 443, 443, 443, 443, 443, 441)
    assert 441 in learned.window


def test_a_learned_range_is_never_treated_as_a_true_empty_end() -> None:
    """The fullest and emptiest readings SEEN are not 100% and 0%.

    A robot in ordinary use never bares its globe, so mapping the observed
    maximum to zero would report empty at a perfectly normal level. Only the
    full end is estimated, and only because people fill to the line.
    """

    learned = Learned(low=440, high=465)
    # Anchored at 90% like the manual reference, so the emptiest seen reads as a
    # believable "getting low", not zero.
    assert litter_level_percent_from_mm(465, full_mm=learned.low) == 48
    assert litter_level_percent_from_mm(440, full_mm=learned.low) == 90


def test_litter_observations_never_touch_the_hopper_hit_count() -> None:
    """That counter gates hopper percentages only.

    A litter bed sits near its low constantly, so counting those would rewrite
    the stored options on every heartbeat for a number nothing reads.
    """
    learned = _litter_gated(Learned(low=440, high=465), 441, 440, 442)
    assert learned.low_hits == 0


def test_a_lower_reading_is_not_floor_confirmation() -> None:
    """A reading below the floor disproves it; it cannot also confirm it."""
    learned = Learned(low=76, high=92, low_hits=2)
    learned.observe(72, bounds=HOPPER_PLAUSIBLE, corroboration=HOPPER_CORROBORATION, count_hits=True)
    assert learned.low_hits == 2, "a new low must not top up the old floor count"
    assert hopper_percent(80, learned) is None


def test_provisional_percent_maps_the_typical_band() -> None:
    """Display-only estimate for an uncalibrated unit: clamped to the band."""

    assert hopper_percent_provisional(84) == 75
    assert hopper_percent_provisional(66) == 0
    assert hopper_percent_provisional(90) == 100
    assert hopper_percent_provisional(50) == 0
    assert hopper_percent_provisional(120) == 100


def test_disagreeing_anomalies_never_vote_a_regime_change_together() -> None:
    """Three rejections only outvote the window when they AGREE — a paw at
    410, a mid-cycle artifact at 520 and another paw are three different
    stories, not one changed world."""
    learned = Learned()
    _litter_gated(learned, 441, 442, 441, 443, 442)  # warm the window; low lands 442
    _litter_gated(learned, 410, 520, 412)  # mixed rejections, no two agreeing
    assert learned.low == 442, "no regime flush may have accepted any of them"
    assert 410 not in learned.window and 520 not in learned.window


def test_a_migrated_record_can_still_deepen_its_floor() -> None:
    """Records persisted before runs existed carry a floor but no run; a first
    reading below that floor counts as the decline it is, or the migrated
    record could never correct downward."""
    learned = Learned(low=66, high=92, low_hits=HOPPER_EMPTY_CONFIRMATIONS)
    _hopper(learned, 61, 61, 61)
    assert learned.low == 61
