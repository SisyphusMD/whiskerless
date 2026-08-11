"""Semantic event extraction from activity readings (ESP 1.4.4 live captures)."""

from __future__ import annotations

from whiskerless.devices.litter_robot_4.codec import ActivityReading, decode_activity_code
from whiskerless.devices.litter_robot_4.events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayMoved,
    HopperDispensed,
    HopperLinkChanged,
    events_from_readings,
)


def _events(*codes: str):
    return events_from_readings([decode_activity_code(c) for c in codes])


def test_cat_weight_from_visit_burst() -> None:
    """Raw 0x01A2 = 418, which is 4.18 lb at the cloud-unit divisor.

    The divisor is 100; it spent a few days at 50 on one anomalous reading
    before a 23h37m capture's seven raws matched the household's cats only
    at /100. See CAT_WEIGHT_DIVISOR.
    """
    events = _events("0x370011", "0x0901A2", "0x6F0013")
    weights = [e for e in events if isinstance(e, CatWeightMeasured)]
    assert weights == [CatWeightMeasured(weight_lb=4.18)]


def test_the_weight_divisor_matches_the_weighed_observation() -> None:
    """Raw 809 must report the ~8.1 lb cat the household scale weighed, not double her."""
    (event,) = _events("0x090329")
    assert isinstance(event, CatWeightMeasured)
    assert event.weight_lb == 8.09


def test_zero_weight_reading_is_ignored() -> None:
    assert _events("0x090000") == []


def test_hopper_dispense_burst() -> None:
    # Real capture 2026-07-27 04:00-04:01Z: three phase-tagged dispense codes.
    events = _events("0x0C010A", "0x0C1059", "0x0C2078")
    assert events == [
        HopperDispensed(raw=0x010A, phase=0, value=0x10A),
        HopperDispensed(raw=0x1059, phase=1, value=0x059),
        HopperDispensed(raw=0x2078, phase=2, value=0x078),
    ]


def test_hopper_fill_gauge_is_dispense_phase_1() -> None:
    # Real captures across the hopper drain: phase-1 value fell 89 -> 66
    # (0x1059 on 07-27 near the ~90% maintain target, 0x1042 on 08-06).
    near_full = _events("0x0C1059")[0]
    assert (near_full.phase, near_full.value) == (1, 89)
    near_empty = _events("0x0C1042")[0]
    assert (near_empty.phase, near_empty.value) == (1, 66)


def test_hopper_link_lost_and_restored() -> None:
    # Real captures: detach/bonnet-lift emit 0x57FFF1; reattach emits positives.
    lost = _events("0x57FFF1")
    assert lost == [HopperLinkChanged(connected=False, raw=0xFFF1)]
    restored = _events("0x57001E", "0x570057")
    assert all(isinstance(e, HopperLinkChanged) and e.connected for e in restored)


def test_unknown_hopper_fault_is_not_reported_as_connected() -> None:
    # 0x57FFE2 (-30) was captured on 1.1.75 around waste-drawer service, on a
    # robot whose hopper was attached. It is a fault we cannot name, so it must
    # read unknown rather than falling through to "connected".
    assert _events("0x57FFE2") == [HopperLinkChanged(connected=None, raw=0xFFE2)]


def test_visit_duration_from_visit_close() -> None:
    # Real capture 2026-07-31 19:14Z: visit closed with 0xBC0011 = 17 s.
    events = _events("0x570013", "0xBC0011", "0xB90001")
    assert [e for e in events if isinstance(e, CatVisitEnded)] == [
        CatVisitEnded(duration_s=17)
    ]


def test_zero_duration_hop_through_is_reported() -> None:
    # Real captures: <5 s forced placements closed with 0xBC0000 and no weight.
    assert _events("0xBC0000") == [CatVisitEnded(duration_s=0)]


def test_button_tare_duration_artifact_is_dropped() -> None:
    # Real capture 2026-07-27 02:14Z: Reset press emitted 0xBC0250 (592) —
    # a tare artifact, not a visit; the plausibility cap drops it.
    assert _events("0xBC0250") == []


def test_drawer_bay_reports_movement_with_the_raw_value() -> None:
    # Any 0x56 reading is one drawer movement, whatever the code.
    assert _events("0x56000A") == [DrawerBayMoved(raw=0x000A)]
    assert _events("0x56001C") == [DrawerBayMoved(raw=0x001C)]


def test_unknown_registers_ignored() -> None:
    # A slice of real telemetry that must never produce events or raise.
    assert _events("0x3C0236", "0x6620F1", "0x6F0013", "0x0B0016", "0x341064") == []


def test_drawer_bay_never_claims_a_direction() -> None:
    """Every value observed across three rounds of narrated pulls.

    10, 11, 13, 14, 15, 16 and 17 all appeared during a mix of removals and
    insertions, and 78 is what a direct read answers with the drawer in OR out.
    Three attempts to name a removal code were each contradicted by the next
    capture, so the event reports movement only. Anything that reintroduces a
    `removed` flag has to explain these values first.
    """
    for value in (10, 11, 13, 14, 15, 16, 17, 28, 78):
        (event,) = events_from_readings([ActivityReading(register=0x56, value=value)])
        assert event == DrawerBayMoved(raw=value)
