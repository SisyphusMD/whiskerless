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
    hopper_percent,
    litter_is_sampleable,
)

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


def test_hopper_learns_from_repeats() -> None:
    learned = Learned()
    for value in (76, 76, 76, 92, 92):
        learned.observe(
            value,
            bounds=HOPPER_PLAUSIBLE,
            corroboration=HOPPER_CORROBORATION,
            count_hits=True,
        )
    assert learned.low == 76
    assert learned.high == 92
    assert learned.span_ok(HOPPER_MIN_SPAN)


def test_round_trips_through_storage() -> None:
    learned = Learned(low=61, high=92, low_candidate=58)
    assert Learned.from_dict(learned.as_dict()) == learned
    assert Learned.from_dict(None) == Learned()
    assert Learned.from_dict({"low": "nonsense"}) == Learned()


def test_a_learned_range_is_never_treated_as_a_true_empty_end() -> None:
    """The fullest and emptiest readings SEEN are not 100% and 0%.

    A robot in ordinary use never bares its globe, so mapping the observed
    maximum to zero would report empty at a perfectly normal level. Only the
    full end is estimated, and only because people fill to the line.
    """
    from whiskerless.devices.litter_robot_4.models import litter_level_percent_from_mm

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
    learned = _litter(Learned(low=440, high=465), 441, 440, 442)
    assert learned.low_hits == 0


def test_a_lower_reading_is_not_floor_confirmation() -> None:
    """A reading below the floor disproves it; it cannot also confirm it."""
    learned = Learned(low=76, high=92, low_hits=2)
    learned.observe(72, bounds=HOPPER_PLAUSIBLE, corroboration=HOPPER_CORROBORATION, count_hits=True)
    assert learned.low_hits == 2, "a new low must not top up the old floor count"
    assert hopper_percent(80, learned) is None
