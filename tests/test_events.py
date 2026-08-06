"""Semantic event extraction from activity readings (ESP 1.4.4 live captures)."""

from __future__ import annotations

from whiskerless.devices.litter_robot_4.codec import decode_activity_code
from whiskerless.devices.litter_robot_4.events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayChanged,
    HopperDispensed,
    HopperLinkChanged,
    events_from_readings,
)


def _events(*codes: str):
    return events_from_readings([decode_activity_code(c) for c in codes])


def test_cat_weight_from_visit_burst() -> None:
    # Real capture 2026-07-27 03:52Z: cat visit emitted 0x0901A2 = 4.18 lb.
    events = _events("0x370011", "0x0901A2", "0x6F0013")
    weights = [e for e in events if isinstance(e, CatWeightMeasured)]
    assert weights == [CatWeightMeasured(weight_lb=4.18)]


def test_zero_weight_reading_is_ignored() -> None:
    assert _events("0x090000") == []


def test_hopper_dispense_burst() -> None:
    # Real capture 2026-07-27 04:00-04:01Z: three phase-tagged dispense codes.
    events = _events("0x0C010A", "0x0C1059", "0x0C2078")
    assert events == [
        HopperDispensed(raw=0x010A),
        HopperDispensed(raw=0x1059),
        HopperDispensed(raw=0x2078),
    ]


def test_hopper_link_lost_and_restored() -> None:
    # Real captures: detach/bonnet-lift emit 0x57FFF1; reattach emits positives.
    lost = _events("0x57FFF1")
    assert lost == [HopperLinkChanged(connected=False, raw=0xFFF1)]
    restored = _events("0x57001E", "0x570057")
    assert all(isinstance(e, HopperLinkChanged) and e.connected for e in restored)


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


def test_drawer_bay_removed_and_inserted() -> None:
    # Real captures: narrated pulls 2026-08-01 and 2026-08-06 both emitted 10
    # on removal; the re-insert code VARIED (14, then 28), so any non-10 value
    # reads as seated.
    assert _events("0x56000A") == [DrawerBayChanged(removed=True, raw=0x000A)]
    assert _events("0x56000E") == [DrawerBayChanged(removed=False, raw=0x000E)]
    assert _events("0x56001C") == [DrawerBayChanged(removed=False, raw=0x001C)]


def test_drawer_bay_unknown_code_reads_as_seated() -> None:
    # 12 fires occasionally with the drawer seated (real capture 2026-08-03) —
    # unknown codes must not latch "removed".
    assert _events("0x56000C") == [DrawerBayChanged(removed=False, raw=0x000C)]


def test_unknown_registers_ignored() -> None:
    # A slice of real telemetry that must never produce events or raise.
    assert _events("0x3C0236", "0x6620F1", "0x6F0013", "0x0B0016", "0x341064") == []
