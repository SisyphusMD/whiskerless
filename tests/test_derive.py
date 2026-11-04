"""Deriving the facts the robot never publishes, from the two streams it does.

The reducer is the whole contract: it must fold a message in without touching
the state it was handed, report what a consumer should persist rather than
persisting anything, and refuse to invent the facts that only some robots own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from whiskerless.devices.litter_robot_4 import LitterRobot4State
from whiskerless.devices.litter_robot_4.calibration import (
    HOPPER_EMPTY_CONFIRMATIONS,
    Learned,
)
from whiskerless.devices.litter_robot_4.codec import decode_activity_code
from whiskerless.devices.litter_robot_4.derive import (
    EXCESS_WEIGHT_AFTER,
    VISIT_CLOSE_GRACE,
    Capability,
    CapabilitySighted,
    CleanCycleCompleted,
    DerivedState,
    Evidence,
    FirmwareChanged,
    HopperFillChanged,
    HopperGaugeStaleChanged,
    LearnedChanged,
    VisitEnded,
    apply_message,
    excess_weight,
    globe_motor_faulted,
    hopper_empty,
    hopper_level_percent,
    litter_scale,
    sighting_stands,
    visit_weight,
)
from whiskerless.devices.litter_robot_4.protocol import ActivityMessage, StateMessage

T0 = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
IDLE = {"robotStatus": 4, "catDetect": 0, "litterLevel": 455}

# One dispense's three codes: phase 0 step marker, phase 1 fill gauge, phase 2
# step marker. Delivered as separate messages on the wire (see the split-burst
# tests); packed into one here where the framing is not what is under test.
BURST = ("0x0C010A", "0x0C1059", "0x0C2078")
FILL_GAUGE = 0x059


def _state(**fields: object) -> StateMessage:
    doc = {**IDLE, **fields}
    return StateMessage(state=LitterRobot4State.from_state_doc(doc), raw=doc)


def _activity(*codes: str) -> ActivityMessage:
    return ActivityMessage(
        readings=[decode_activity_code(code) for code in codes], raw={"data": list(codes)}
    )


def _seen(state: DerivedState, message: object, now: datetime = T0) -> DerivedState:
    """Fold a message in and keep only the state, for multi-step arrangements."""
    assert isinstance(message, (StateMessage, ActivityMessage))
    return apply_message(state, message, now).state


def _sightings(update: object) -> dict[Capability, Evidence]:
    assert hasattr(update, "effects")
    return {
        e.capability: e.evidence
        for e in update.effects  # type: ignore[attr-defined]
        if isinstance(e, CapabilitySighted)
    }


# --- the reducer never touches what it was handed -----------------------------
def test_folding_a_message_leaves_the_original_state_alone() -> None:
    before = DerivedState()
    after = apply_message(before, _state(catDetect=1), T0).state
    assert after is not before
    assert before.beam_broken_at is None and after.beam_broken_at == T0


def test_the_learned_window_is_copied_too_not_shared() -> None:
    # replace() alone would hand the copy the same list object, so a reading
    # folded into the copy would appear in the state the caller kept.
    before = DerivedState()
    after = apply_message(before, _state(), T0).state
    assert after.learned_litter.window == [455]
    assert before.learned_litter.window == []


# --- state documents -----------------------------------------------------------
def test_a_state_document_always_counts_as_a_change() -> None:
    assert apply_message(DerivedState(), _state(), T0).changed


def test_occupancy_stamps_the_beam() -> None:
    assert apply_message(DerivedState(), _state(catDetect=1), T0).state.beam_broken_at == T0


def test_an_arrival_stamps_a_visit_and_proves_the_robot_reports_them() -> None:
    empty = _seen(DerivedState(), _state(catDetect=0))
    update = apply_message(empty, _state(catDetect=1), T0)
    assert update.state.last_cat_visit == T0
    assert _sightings(update) == {Capability.CAT_VISIT: Evidence.OCCUPANCY}


def test_a_first_document_arriving_mid_visit_is_not_an_arrival() -> None:
    # Presence, not an edge: the cat may have been in there for minutes.
    update = apply_message(DerivedState(), _state(catDetect=1), T0)
    assert update.state.last_cat_visit is None
    assert not _sightings(update)


def test_the_visit_sighting_is_recorded_once() -> None:
    empty = _seen(DerivedState(), _state(catDetect=0))
    seen = _seen(empty, _state(catDetect=1))
    again = _seen(seen, _state(catDetect=0))
    update = apply_message(again, _state(catDetect=1), T0 + timedelta(hours=1))
    assert not _sightings(update)
    assert update.state.sightings == {Capability.CAT_VISIT: Evidence.OCCUPANCY}


def test_a_loaded_scale_opens_a_run_and_a_clear_one_closes_it() -> None:
    loaded = _seen(DerivedState(), _state(catDetect=2))
    assert loaded.scale_loaded_since == T0
    held = _seen(loaded, _state(catDetect=2), T0 + timedelta(minutes=5))
    assert held.scale_loaded_since == T0, "a continuing run keeps its start"
    assert _seen(held, _state(catDetect=0)).scale_loaded_since is None


def test_a_document_without_the_bit_leaves_the_run_alone() -> None:
    # A cloud-style boolean carries no bit information, so scale_loaded is None
    # and says nothing either way — it must not close a real run.
    loaded = _seen(DerivedState(), _state(catDetect=2))
    assert _seen(loaded, _state(catDetect="unknown")).scale_loaded_since == T0


def test_a_firmware_change_is_reported_but_the_first_sighting_is_not() -> None:
    first = apply_message(DerivedState(), _state(espFirmware="1.1.75"), T0)
    assert not any(isinstance(e, FirmwareChanged) for e in first.effects)
    assert first.state.esp_firmware == "1.1.75"
    update = apply_message(first.state, _state(espFirmware="1.4.4"), T0)
    assert FirmwareChanged("1.4.4") in update.effects


def test_the_same_firmware_is_not_a_change() -> None:
    first = _seen(DerivedState(), _state(espFirmware="1.4.4"))
    update = apply_message(first, _state(espFirmware="1.4.4"), T0)
    assert not any(isinstance(e, FirmwareChanged) for e in update.effects)


def test_a_document_with_no_firmware_field_keeps_the_known_build() -> None:
    known = _seen(DerivedState(), _state(espFirmware="1.4.4"))
    assert _seen(known, _state()).esp_firmware == "1.4.4"


# --- learning the litter scale from state documents ---------------------------
def test_a_settled_reading_teaches_the_scale_and_asks_to_be_persisted() -> None:
    update = apply_message(DerivedState(), _state(litterLevel=440), T0)
    assert LearnedChanged() in update.effects
    assert update.state.learned_litter.low_candidate == 440


def test_a_redelivery_seconds_later_is_not_a_second_observation() -> None:
    first = _seen(DerivedState(), _state(litterLevel=440))
    second = _seen(first, _state(litterLevel=440), T0 + timedelta(seconds=5))
    assert second.learned_litter.low is None, "one reading corroborated itself"
    assert second.last_litter_sample_at == T0


def test_an_independent_second_reading_confirms_the_anchor() -> None:
    first = _seen(DerivedState(), _state(litterLevel=440))
    second = _seen(first, _state(litterLevel=441), T0 + timedelta(minutes=5))
    assert second.learned_litter.low == 441


def test_a_cat_in_the_globe_teaches_nothing() -> None:
    update = apply_message(DerivedState(), _state(catDetect=1, litterLevel=253), T0)
    assert not any(isinstance(e, LearnedChanged) for e in update.effects)
    assert update.state.learned_litter.low_candidate is None


# --- activity: the events only this stream carries -----------------------------
def test_a_weight_proves_both_the_weight_and_the_visit() -> None:
    update = apply_message(DerivedState(), _activity("0x090320"), T0)
    assert update.changed
    assert update.state.cat_weight_lb == 8.0
    assert update.state.last_cat_visit == T0
    assert _sightings(update) == {
        Capability.PET_WEIGHT: Evidence.CAT_WEIGHT,
        Capability.CAT_VISIT: Evidence.CAT_WEIGHT,
    }


def test_a_dispense_burst_proves_a_hopper_and_reports_its_gauge() -> None:
    update = apply_message(DerivedState(), _activity(*BURST), T0)
    assert update.state.hopper_connected is True
    assert update.state.hopper_fill_raw == FILL_GAUGE
    assert update.state.last_hopper_dispensed == T0
    assert HopperFillChanged(FILL_GAUGE) in update.effects
    assert _sightings(update) == {Capability.HOPPER: Evidence.DISPENSE}


def test_a_lone_dispense_code_is_a_register_read_not_a_hopper() -> None:
    # A type-1 READ of 0x0C decodes to a single HopperDispensed, and taking that
    # as proof would grow four hopper entities on a robot that has none.
    update = apply_message(DerivedState(), _activity("0x0C1059"), T0)
    assert update.state.hopper_connected is None
    assert update.state.hopper_fill_raw is None
    assert not update.effects


def test_a_dispense_split_across_messages_still_proves_the_hopper() -> None:
    # How every captured dispense actually arrives, on both firmwares: three
    # single-reading messages, the step marker ~20 s before the fill gauge. The
    # burst is the same evidence however it is framed across messages.
    state = _seen(DerivedState(), _activity("0x0C010A"), T0)
    assert state.hopper_connected is None, "one phase alone is still just a read"
    update = apply_message(state, _activity("0x0C1059"), T0 + timedelta(seconds=20))
    assert update.state.hopper_connected is True
    assert update.state.hopper_fill_raw == FILL_GAUGE
    assert HopperFillChanged(FILL_GAUGE) in update.effects
    assert _sightings(update) == {Capability.HOPPER: Evidence.DISPENSE}
    # The trailing step marker lands moments later and adds nothing new.
    update = apply_message(
        update.state, _activity("0x0C2078"), T0 + timedelta(seconds=20.2)
    )
    assert not any(isinstance(e, HopperFillChanged) for e in update.effects)


def test_a_burst_that_loses_its_gauge_message_still_proves_the_hopper() -> None:
    # The phases are separate publishes, so the middle one can simply not
    # arrive. The two markers still prove litter was delivered; there is just no
    # fill reading to apply, and inventing one from the markers would be worse
    # than reporting nothing.
    state = _seen(DerivedState(), _activity("0x0C010A"), T0)
    update = apply_message(state, _activity("0x0C2078"), T0 + timedelta(seconds=20))
    assert update.state.hopper_connected is True
    assert _sightings(update) == {Capability.HOPPER: Evidence.DISPENSE}
    assert update.state.hopper_fill_raw is None
    assert not any(isinstance(e, HopperFillChanged) for e in update.effects)


def test_the_trailing_phase_does_not_stamp_the_dispense_twice() -> None:
    # The burst proves on its second phase, and a third one follows moments
    # later. `last_hopper_dispensed` is a timestamp somebody reads, so it must
    # not creep forward for a dispense that has already been counted.
    state = DerivedState()
    for code, offset in (("0x0C010A", 0), ("0x0C1059", 20)):
        state = _seen(state, _activity(code), T0 + timedelta(seconds=offset))
    proved_at = state.last_hopper_dispensed
    assert proved_at == T0 + timedelta(seconds=20)
    update = apply_message(state, _activity("0x0C2078"), T0 + timedelta(seconds=20.2))
    assert not update.changed
    assert update.state.last_hopper_dispensed == proved_at
    # A real dispense a cycle later is a different matter, gauge and all.
    state = _seen(update.state, _activity("0x0C010A"), T0 + timedelta(minutes=10))
    state = _seen(state, _activity("0x0C1055"), T0 + timedelta(minutes=10, seconds=20))
    assert state.last_hopper_dispensed == T0 + timedelta(minutes=10, seconds=20)
    assert state.hopper_fill_raw == 0x055


def test_repeated_reads_of_the_same_phase_prove_nothing() -> None:
    # Polling 0x0C returns whatever the register last held — the same phase
    # every time. Only distinct phases look like a dispense.
    state = _seen(DerivedState(), _activity("0x0C1059"), T0)
    update = apply_message(state, _activity("0x0C1059"), T0 + timedelta(seconds=10))
    assert update.state.hopper_connected is None
    assert update.state.hopper_fill_raw is None
    assert not update.effects


def test_phases_farther_apart_than_the_burst_window_prove_nothing() -> None:
    # Two lone reads that happen to differ can only masquerade as a burst if
    # they land inside the window a real burst fits in.
    state = _seen(DerivedState(), _activity("0x0C010A"), T0)
    update = apply_message(state, _activity("0x0C1059"), T0 + timedelta(minutes=5))
    assert update.state.hopper_connected is None
    assert not update.effects


def test_an_unchanged_gauge_is_not_reported_as_a_new_reading() -> None:
    first = _seen(DerivedState(), _activity(*BURST))
    update = apply_message(first, _activity(*BURST), T0 + timedelta(hours=1))
    assert not any(isinstance(e, HopperFillChanged) for e in update.effects)
    assert update.changed, "the dispense itself still happened"


def test_dispenses_a_cycle_apart_flatlining_confirm_the_floor() -> None:
    state = DerivedState(learned_hopper=Learned(low=61, high=100, run_value=92))
    for step in range(HOPPER_EMPTY_CONFIRMATIONS):
        state = _seen(state, _activity(*BURST), T0 + timedelta(hours=step))
    assert state.learned_hopper.low == FILL_GAUGE
    assert hopper_empty(state) is True


def test_a_redelivered_dispense_cannot_corroborate_itself() -> None:
    first = _seen(DerivedState(), _activity(*BURST))
    second = _seen(first, _activity(*BURST), T0 + timedelta(seconds=5))
    assert second.learned_hopper.run_length == 1
    assert second.last_hopper_sample_at == T0


def test_a_visit_close_needs_a_body_in_the_beam() -> None:
    # 0xBC fires for a Reset press too, which is why the beam gates it.
    update = apply_message(DerivedState(), _activity("0xBC000F"), T0)
    assert update.state.last_visit_duration_s is None
    assert not update.changed


def test_a_visit_close_behind_the_beam_is_the_cat_leaving() -> None:
    occupied = _seen(DerivedState(), _state(catDetect=1))
    update = apply_message(occupied, _activity("0xBC000F"), T0 + timedelta(seconds=1))
    assert update.state.last_visit_duration_s == 15
    assert update.state.last_cat_visit == T0 + timedelta(seconds=1)
    assert update.state.beam_broken_at is None, "that visit is spent"
    assert _sightings(update) == {
        Capability.VISIT_DURATION: Evidence.VISIT_DURATION,
        Capability.CAT_VISIT: Evidence.VISIT_DURATION,
    }


def test_an_arm_in_the_beam_does_not_license_a_close_minutes_later() -> None:
    touched = _seen(DerivedState(), _state(catDetect=1))
    late = T0 + VISIT_CLOSE_GRACE + timedelta(seconds=16)  # 15 s claimed, 16 s past it
    assert apply_message(touched, _activity("0xBC000F"), late).state.last_visit_duration_s is None


def test_a_long_visit_closes_against_the_break_that_started_it() -> None:
    """State documents arrive minutes apart, so the break that stamps a visit is
    the one at its start — a window that ignored the claimed duration dropped
    every visit longer than itself, which is the cats that sit longest."""
    arrived = _seen(DerivedState(), _state(catDetect=1))
    close = T0 + timedelta(seconds=240)
    update = apply_message(arrived, _activity(f"0xBC{240:04X}"), close)
    assert update.state.last_visit_duration_s == 240


def test_a_globe_fault_is_a_change_and_holding_it_is_not() -> None:
    raised = apply_message(DerivedState(), _activity("0x350001"), T0)
    assert raised.changed and raised.state.globe_motor_fault == 1
    assert not apply_message(raised.state, _activity("0x350001"), T0).changed
    assert apply_message(raised.state, _activity("0x350000"), T0).state.globe_motor_fault == 0


def test_the_drawer_moving_proves_the_robot_reports_it() -> None:
    update = apply_message(DerivedState(), _activity("0x56000B"), T0)
    assert update.state.drawer_last_moved == T0
    assert _sightings(update) == {Capability.DRAWER: Evidence.DRAWER_MOVED}


def test_unmapped_telemetry_changes_nothing() -> None:
    # The activity stream carries a large amount of unmapped traffic; none of it
    # may wake a consumer.
    update = apply_message(DerivedState(), _activity("0x330001", "0x4A0002"), T0)
    assert not update.changed and not update.effects


def test_a_link_report_derives_nothing() -> None:
    # 0x57 positives arrive with the hopper sitting on a bench.
    update = apply_message(DerivedState(), _activity("0x570001"), T0)
    assert update.state.hopper_connected is None and not update.changed


# --- the read model ------------------------------------------------------------
def test_the_users_own_measurements_win() -> None:
    state = DerivedState(learned_litter=Learned(low=430, high=470))
    assert litter_scale(state, full_mm=435, empty_mm=465) == (435, 465)


def test_the_learned_minimum_stands_in_for_a_reference_and_never_for_empty() -> None:
    state = DerivedState(learned_litter=Learned(low=430, high=470))
    assert litter_scale(state) == (430, None)


def test_the_hopper_reads_nothing_until_it_has_reported_a_gauge() -> None:
    state = DerivedState(learned_hopper=Learned(low=61, high=90, low_hits=3))
    assert hopper_level_percent(state) is None
    assert hopper_empty(state) is None


def _settle(state: DerivedState, *readings: int) -> tuple[DerivedState, list[object]]:
    """Fold in settled litter readings five minutes apart, as a robot publishes them."""
    effects: list[object] = []
    for i, mm in enumerate(readings):
        update = apply_message(
            state, _state(**{**IDLE, "litterLevel": mm}), T0 + timedelta(minutes=5 * i)
        )
        state = update.state
        effects += update.effects
    return state, effects


EMPTY_HOPPER = {"hopper_fill_raw": 60, "learned_hopper": Learned(low=59, high=81, low_hits=3)}


def test_a_top_up_stops_an_empty_gauge_from_being_believed() -> None:
    """Filling the globe stops the dispenses that would have re-read the hopper."""
    state, effects = _settle(DerivedState(**EMPTY_HOPPER), 470, 470, *[440] * 5)
    assert HopperGaugeStaleChanged(True) in effects
    assert hopper_empty(state) is False
    assert hopper_level_percent(state) is None


def test_a_gauge_is_believed_until_the_step_has_held() -> None:
    state, effects = _settle(DerivedState(**EMPTY_HOPPER), 470, *[440] * 4)
    assert not any(isinstance(e, HopperGaugeStaleChanged) for e in effects)
    assert hopper_empty(state) is True


def test_a_passing_reading_breaks_a_step() -> None:
    """A paw over the sensor reads like a full globe for as long as it stays there."""
    state, effects = _settle(
        DerivedState(**EMPTY_HOPPER), 470, 440, 440, 440, 440, 470, 440, 440, 440, 440
    )
    assert not any(isinstance(e, HopperGaugeStaleChanged) for e in effects)
    assert hopper_empty(state) is True


def test_a_slow_rise_is_not_a_top_up() -> None:
    _, effects = _settle(DerivedState(**EMPTY_HOPPER), *range(470, 430, -5))
    assert not any(isinstance(e, HopperGaugeStaleChanged) for e in effects)


def test_litter_taken_out_is_not_a_top_up_nor_is_the_way_back() -> None:
    """Steps down move the baseline, and a scoop must not make the old level a fill."""
    state, effects = _settle(DerivedState(**EMPTY_HOPPER), 440, *[470] * 5, 470, 470)
    assert not any(isinstance(e, HopperGaugeStaleChanged) for e in effects)
    assert state.litter_baseline_mm == 470


def test_a_top_up_is_announced_once() -> None:
    _, effects = _settle(DerivedState(**EMPTY_HOPPER), 470, *[440] * 5, *[410] * 5)
    assert effects.count(HopperGaugeStaleChanged(True)) == 1


def test_a_dispense_after_a_top_up_reads_the_hopper_again() -> None:
    state, _ = _settle(DerivedState(**EMPTY_HOPPER), 470, *[440] * 5)
    now = T0 + timedelta(hours=1)
    for code in BURST:
        update = apply_message(state, _activity(code), now)
        state = update.state
    assert state.hopper_gauge_stale is False
    assert hopper_level_percent(state) is not None


def test_implausible_readings_are_not_a_top_up() -> None:
    state, effects = _settle(DerivedState(**EMPTY_HOPPER), 600, *[470] * 5, *[0] * 5)
    assert not any(isinstance(e, HopperGaugeStaleChanged) for e in effects)
    assert state.litter_baseline_mm == 470


def test_a_top_up_survives_a_restart_and_the_baseline_does_not() -> None:
    """The snapshot is old by the time it is read, so its baseline would invent a step."""
    state, _ = _settle(DerivedState(**EMPTY_HOPPER), 470, 440)
    state.hopper_gauge_stale = True
    restored = DerivedState.from_dict(state.as_dict())
    assert restored.hopper_gauge_stale is True
    assert restored.litter_baseline_mm is None
    assert restored.litter_step_samples == 0


def test_a_gauge_against_a_confirmed_scale_is_a_percentage() -> None:
    state = DerivedState(
        hopper_fill_raw=76, learned_hopper=Learned(low=61, high=91, low_hits=3)
    )
    assert hopper_level_percent(state) == 50
    assert hopper_empty(state) is False


@pytest.mark.parametrize(
    ("activity", "field_value", "restored", "expected"),
    [
        (1, 0, None, True),  # the stream saw the edge the field never mirrors
        (0, 1, None, True),  # …and the field is still believed when it does
        (0, 0, None, False),
        (None, 0, True, True),  # a restored fault outranks the field's cheerful 0
        (None, 0, False, False),
        (None, None, None, None),
        (None, 1, None, True),
    ],
)
def test_a_globe_fault_from_either_source_is_a_fault(
    activity: int | None, field_value: int | None, restored: bool | None, expected: bool | None
) -> None:
    doc = {**IDLE} if field_value is None else {**IDLE, "globeMotorFaultStatus": field_value}
    robot = LitterRobot4State.from_state_doc(doc)
    state = DerivedState(globe_motor_fault=activity, globe_fault_restored=restored)
    assert globe_motor_faulted(state, robot) is expected


def test_a_completed_cycle_retires_a_carried_fault() -> None:
    # Otherwise a verdict carried past the clear edge re-restores itself forever:
    # the state field's 0 is distrusted by design, so nothing else can retire it.
    carried = DerivedState(globe_fault_restored=True)
    running = _seen(carried, _state(odometerCleanCycles=1200))
    assert running.globe_fault_restored is True, "the first document only sets the baseline"
    assert _seen(running, _state(odometerCleanCycles=1200)).globe_fault_restored is True
    assert _seen(running, _state(odometerCleanCycles=1201)).globe_fault_restored is False


def test_a_cycle_does_not_retire_a_fault_the_stream_itself_reported() -> None:
    # A fault DURING a cycle raises its own edge, which outranks the carried
    # verdict anyway — clearing on the odometer would silence a live fault.
    live = DerivedState(globe_fault_restored=True, globe_motor_fault=1, cycles_seen=1200)
    assert _seen(live, _state(odometerCleanCycles=1201)).globe_fault_restored is True


def test_a_robot_that_reports_no_odometer_leaves_the_baseline_alone() -> None:
    carried = DerivedState(globe_fault_restored=True)
    assert _seen(carried, _state()).cycles_seen is None


def test_a_clear_pan_retires_a_carried_excess_weight_answer() -> None:
    # Left standing it would alarm at second zero of every later loaded run.
    carried = DerivedState(excess_weight_restored=True)
    assert _seen(carried, _state(catDetect=0)).excess_weight_restored is None


def test_excess_weight_needs_the_full_thirty_minutes() -> None:
    robot = LitterRobot4State.from_state_doc({**IDLE, "catDetect": 2})
    state = DerivedState(scale_loaded_since=T0)
    assert excess_weight(state, robot, T0 + timedelta(minutes=29)) is False
    assert excess_weight(state, robot, T0 + EXCESS_WEIGHT_AFTER) is True


def test_a_restored_alarm_survives_the_restart_that_forgot_when_it_started() -> None:
    robot = LitterRobot4State.from_state_doc({**IDLE, "catDetect": 2})
    state = DerivedState(scale_loaded_since=T0, excess_weight_restored=True)
    assert excess_weight(state, robot, T0) is True


def test_a_clear_pan_is_a_no_and_an_absent_bit_is_unknown() -> None:
    clear = LitterRobot4State.from_state_doc({**IDLE, "catDetect": 0})
    assert excess_weight(DerivedState(), clear, T0) is False
    silent = LitterRobot4State.from_state_doc({**IDLE, "catDetect": "unknown"})
    assert excess_weight(DerivedState(), silent, T0) is None


# --- what a change to the standard of proof retires ----------------------------
def test_a_sighting_stands_on_evidence_its_capability_accepts() -> None:
    assert sighting_stands(Capability.HOPPER, Evidence.DISPENSE)
    assert not sighting_stands(Capability.HOPPER, Evidence.CAT_WEIGHT), "a weight is not a hopper"


def test_a_restored_duration_is_never_good_enough() -> None:
    # Earlier builds recorded this one from evidence since proven wrong, so the
    # restored value is itself the suspect thing.
    assert sighting_stands(Capability.PET_WEIGHT, Evidence.RESTORED)
    assert not sighting_stands(Capability.VISIT_DURATION, Evidence.RESTORED)


def test_a_sighting_that_records_no_evidence_stands() -> None:
    # The bare flag of a build that recorded nothing: already re-derived by the
    # one-off sweeps that retired the standards known to be wrong.
    assert sighting_stands(Capability.HOPPER, True)


def test_evidence_from_a_newer_build_is_trusted_not_judged() -> None:
    # A downgrade must not throw away what a later, stricter standard accepted.
    assert sighting_stands(Capability.HOPPER, "a_kind_from_the_future")


# --- carrying the derived state across a restart -------------------------------
def test_the_state_round_trips_through_storage() -> None:
    state = _seen(_seen(DerivedState(), _state(catDetect=1)), _activity(*BURST))
    state.cat_weight_lb = 8.25
    state.drawer_last_moved = T0
    restored = DerivedState.from_dict(state.as_dict())
    assert restored == state


def test_a_pending_burst_survives_a_round_trip_through_storage() -> None:
    """A half-assembled burst is state like any other, so it round-trips.

    What this does NOT claim is that Home Assistant survives a restart mid-burst:
    the coordinator writes the derived snapshot only when a sighting fires, and
    the first phase of a burst fires nothing. A restart inside the ~20 s gap
    therefore costs that one dispense, and the next one proves the hopper. This
    is the library keeping its half of the contract, so a consumer that does
    persist at that moment loses nothing.
    """
    state = _seen(DerivedState(), _activity("0x0C010A"), T0)
    assert state.pending_dispense, "the first phase has to be kept somewhere"
    restored = DerivedState.from_dict(state.as_dict())
    assert restored == state
    update = apply_message(restored, _activity("0x0C1059"), T0 + timedelta(seconds=20))
    assert update.state.hopper_connected is True
    assert update.state.hopper_fill_raw == FILL_GAUGE


def test_anything_that_is_not_a_stored_state_reads_as_a_fresh_one() -> None:
    assert DerivedState.from_dict("nonsense") == DerivedState()
    assert DerivedState.from_dict({"sightings": "nonsense"}).sightings == {}
    assert DerivedState.from_dict({"pending_dispense": "nonsense"}).pending_dispense == {}
    # A half-written burst must not take the whole stored state down with it,
    # and a phase the wire cannot produce must not be admitted as evidence: it
    # would count toward the two-phase proof and let one later register read
    # look like a dispense. Phase is 4 bits, value is 12.
    assert DerivedState.from_dict(
        {"pending_dispense": {"0": 266, "nope": "nope", "99": 1, "1": 0x1FFF}}
    ).pending_dispense == {0: 266}


def test_a_sighting_this_version_does_not_recognize_is_dropped() -> None:
    # Forward compatibility runs one way: a newer build may have proven a
    # capability with evidence this one has never heard of, and guessing what it
    # meant is worse than re-proving it.
    raw = {"sightings": {"hopper": "dispense", "teleporter": "vibes", "drawer": "vibes"}}
    assert DerivedState.from_dict(raw).sightings == {Capability.HOPPER: Evidence.DISPENSE}


def test_stored_junk_never_becomes_a_derived_fact() -> None:
    raw = {
        "cat_weight_lb": "heavy",
        "last_cat_visit": "not a time",
        "last_visit_duration_s": True,
        "hopper_connected": "yes",
        "hopper_fill_raw": None,
        "globe_motor_fault": "faulted",
        "occupied": 1,
        "esp_firmware": 144,
        "last_hopper_sample_at": 12345,
    }
    assert DerivedState.from_dict(raw) == DerivedState()


def test_a_datetime_stored_as_itself_is_taken_as_read() -> None:
    # Consumers that keep the state in memory hand back real datetimes.
    assert DerivedState.from_dict({"beam_broken_at": T0}).beam_broken_at == T0


# --- the end of a clean cycle -------------------------------------------------
def _cycles(update: object) -> list[CleanCycleCompleted]:
    assert hasattr(update, "effects")
    return [e for e in update.effects if isinstance(e, CleanCycleCompleted)]


def test_a_cycle_watched_from_start_to_ready_is_announced_once() -> None:
    state = _seen(DerivedState(), _state(robotStatus=10, odometerCleanCycles=9128))
    update = apply_message(state, _state(robotStatus=4, odometerCleanCycles=9128), T0)
    assert _cycles(update) == [CleanCycleCompleted(9128)]
    # A second ready document is not a second cycle.
    assert _cycles(apply_message(update.state, _state(robotStatus=4), T0)) == []


def test_a_cat_pause_mid_cycle_does_not_end_it() -> None:
    """A pause reports other statuses and then clean_cycle again; only ready ends it."""
    state = _seen(DerivedState(), _state(robotStatus=10))
    for status in (7, 10):
        update = apply_message(state, _state(robotStatus=status), T0)
        assert _cycles(update) == []
        state = update.state
    assert len(_cycles(apply_message(state, _state(robotStatus=4), T0))) == 1


def test_the_odometer_moving_is_not_the_end_of_a_cycle() -> None:
    """It advances as a cycle starts, so it must not be read as one finishing."""
    state = _seen(DerivedState(), _state(robotStatus=4, odometerCleanCycles=9127))
    assert _cycles(apply_message(state, _state(robotStatus=10, odometerCleanCycles=9128), T0)) == []


def test_a_cycle_not_seen_starting_is_not_announced() -> None:
    """The first document after a restart says where the robot is, not what it just did."""
    assert _cycles(apply_message(DerivedState(), _state(robotStatus=4), T0)) == []


def test_a_running_cycle_is_not_carried_over_a_restart() -> None:
    running = _seen(DerivedState(), _state(robotStatus=10))
    assert running.cycle_running is True
    assert "cycle_running" not in running.as_dict()
    restored = DerivedState.from_dict(running.as_dict())
    assert _cycles(apply_message(restored, _state(robotStatus=4), T0)) == []


# --- the end of a cat visit ---------------------------------------------------
def _visits(update: object) -> list[VisitEnded]:
    assert hasattr(update, "effects")
    return [e for e in update.effects if isinstance(e, VisitEnded)]


def _walk(*steps: tuple[dict[str, object], int]) -> tuple[DerivedState, list[VisitEnded]]:
    """Fold (fields, seconds-after-T0) state documents and collect visits."""
    state, seen = DerivedState(), []
    for fields, at in steps:
        update = apply_message(state, _state(**fields), T0 + timedelta(seconds=at))
        state, seen = update.state, seen + _visits(update)
    return state, seen


def test_a_visit_ends_when_the_sensors_clear_during_the_countdown() -> None:
    _, visits = _walk(
        ({"robotStatus": 25, "catDetect": 3}, 0),
        # The countdown starts with the cat still on the scale: not the end yet.
        ({"robotStatus": 7, "catDetect": 3}, 12),
        ({"robotStatus": 7, "catDetect": 0}, 40),
        ({"robotStatus": 7, "catDetect": 0}, 60),
    )
    assert visits == [VisitEnded(started=T0, ended=T0 + timedelta(seconds=40))]
    assert visits[0].duration_s == 40


def test_a_detection_that_falls_back_to_ready_is_not_a_visit() -> None:
    """A hand on the robot or a false trigger: the robot never counted it down."""
    _, visits = _walk(
        ({"robotStatus": 25, "catDetect": 2}, 0),
        ({"robotStatus": 4, "catDetect": 0}, 5),
        ({"robotStatus": 7, "catDetect": 0}, 9),
    )
    assert visits == []


def test_a_countdown_with_no_detection_before_it_ends_nothing() -> None:
    """The first document after a restart can land mid-countdown."""
    _, visits = _walk(({"robotStatus": 7, "catDetect": 0}, 0))
    assert visits == []


def test_an_open_visit_is_not_carried_over_a_restart() -> None:
    state, _ = _walk(({"robotStatus": 25, "catDetect": 3}, 0))
    assert state.visit_started_at is not None
    assert "visit_started_at" not in state.as_dict()


def test_the_weight_belongs_to_the_visit_only_inside_its_window() -> None:
    visit = VisitEnded(started=T0, ended=T0 + timedelta(seconds=40))
    weighed = DerivedState(cat_weight_lb=9.4, weight_measured_at=T0 + timedelta(seconds=45))
    assert visit_weight(weighed, visit) == 9.4
    earlier = DerivedState(cat_weight_lb=9.4, weight_measured_at=T0 - timedelta(seconds=1))
    assert visit_weight(earlier, visit) is None
    late = DerivedState(cat_weight_lb=9.4, weight_measured_at=T0 + timedelta(seconds=56))
    assert visit_weight(late, visit) is None
    assert visit_weight(DerivedState(), visit) is None


def test_a_weight_reading_records_when_it_arrived() -> None:
    update = apply_message(DerivedState(), _activity("0x0903AC"), T0)
    assert update.state.weight_measured_at == T0


def test_a_weight_after_a_newer_visit_began_is_not_the_earlier_ones() -> None:
    first = VisitEnded(started=T0, ended=T0 + timedelta(seconds=40))
    state = DerivedState(
        cat_weight_lb=12.0,
        weight_measured_at=T0 + timedelta(seconds=50),
        latest_visit_started_at=T0 + timedelta(seconds=45),
    )
    assert visit_weight(state, first) is None
    second = VisitEnded(started=T0 + timedelta(seconds=45), ended=T0 + timedelta(seconds=48))
    assert visit_weight(state, second) == 12.0
