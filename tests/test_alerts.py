"""When each replacement for a Whisker app notification fires, and when it does not.

The cost of getting this wrong is a phone buzzing for nothing, or silence while a
robot sits stopped, so the hold times and the "cannot tell" cases matter as much as
the happy path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from whiskerless.devices.litter_robot_4 import LitterRobot4State
from whiskerless.devices.litter_robot_4.alerts import (
    HOLD,
    URGENT,
    Alert,
    AlertSettings,
    AlertTracker,
    MomentTracker,
    Reminders,
    Snapshot,
    conditions,
    describe,
)
from whiskerless.devices.litter_robot_4.derive import (
    Capability,
    CleanCycleCompleted,
    DerivedState,
    Evidence,
    VisitEnded,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SETTINGS = AlertSettings()
IDLE = {"robotStatus": 4, "catDetect": 0, "litterLevel": 455, "DFILevelPercent": 40}


def _snap(online: bool = True, derived: DerivedState | None = None, **fields: object) -> Snapshot:
    return Snapshot(
        robot=LitterRobot4State.from_state_doc({**IDLE, **fields}),
        derived=derived or DerivedState(),
        online=online,
        litter_percent=60,
    )


def _truth(snap: Snapshot, alert: Alert, now: datetime = T0) -> object:
    return conditions(snap, SETTINGS, now)[alert][0]


# --- conditions -----------------------------------------------------------------
def test_an_idle_robot_raises_nothing() -> None:
    raw = conditions(_snap(), SETTINGS, T0)
    assert [a for a, (truth, _) in raw.items() if truth] == []


def test_a_robot_we_cannot_hear_reports_offline_and_nothing_else() -> None:
    """Its last drawer reading is old news, not a reason to clear or raise."""
    raw = conditions(_snap(online=False, isDFIFull=1), SETTINGS, T0)
    assert raw[Alert.OFFLINE][0] is True
    assert raw[Alert.DRAWER_FULL][0] is None
    assert raw[Alert.GLOBE_FAULT][0] is None


def test_the_drawer_alerts_follow_the_gauge_but_not_a_reset_zero() -> None:
    assert _truth(_snap(isDFIFull=1), Alert.DRAWER_FULL) is True
    assert _truth(_snap(DFILevelPercent=85), Alert.DRAWER_LEVEL) is True
    assert _truth(_snap(DFILevelPercent=50), Alert.DRAWER_LEVEL) is False
    assert _truth(_snap(DFILevelPercent=0, isDFIResetPending=1), Alert.DRAWER_LEVEL) is None


def test_a_level_alert_clears_only_ten_points_back_past_its_threshold() -> None:
    """The gauges wobble a few points on a box nobody touched; a wobble is not news."""
    drawer, litter = Alert.DRAWER_LEVEL, Alert.LITTER_LOW
    raised = {drawer, litter}

    def truth(snap: Snapshot, alert: Alert, active: set[Alert]) -> object:
        return conditions(snap, SETTINGS, T0, active)[alert][0]

    assert truth(_snap(DFILevelPercent=77), drawer, set()) is False
    assert truth(_snap(DFILevelPercent=77), drawer, raised) is True
    assert truth(_snap(DFILevelPercent=70), drawer, raised) is False
    low = Snapshot(robot=_snap().robot, derived=DerivedState(), online=True, litter_percent=35)
    assert truth(low, litter, set()) is False
    assert truth(low, litter, raised) is True
    refilled = Snapshot(robot=_snap().robot, derived=DerivedState(), online=True, litter_percent=40)
    assert truth(refilled, litter, raised) is False


def test_litter_low_is_not_judged_while_the_globe_turns() -> None:
    low = Snapshot(robot=LitterRobot4State.from_state_doc(IDLE), derived=DerivedState(),
                   online=True, litter_percent=20)
    assert _truth(low, Alert.LITTER_LOW) is True
    turning = Snapshot(robot=LitterRobot4State.from_state_doc({**IDLE, "robotStatus": 10}),
                       derived=DerivedState(), online=True, litter_percent=20)
    assert _truth(turning, Alert.LITTER_LOW) is None


def test_litter_low_is_not_judged_during_a_visit_or_the_countdown_after_it() -> None:
    for status in (25, 6, 7):
        visit = Snapshot(robot=LitterRobot4State.from_state_doc({**IDLE, "robotStatus": status}),
                         derived=DerivedState(), online=True, litter_percent=7)
        assert _truth(visit, Alert.LITTER_LOW) is None


def test_a_globe_fault_carries_its_reported_cause() -> None:
    raw = conditions(_snap(derived=DerivedState(globe_motor_fault=6)), SETTINGS, T0)
    assert raw[Alert.GLOBE_FAULT] == (True, {"cause": "pinch"})
    assert "pinch" in describe(Alert.GLOBE_FAULT, True, raw[Alert.GLOBE_FAULT][1])


def test_hopper_alerts_only_exist_on_a_robot_seen_with_a_hopper() -> None:
    bare = DerivedState(hopper_connected=False)
    assert _truth(_snap(derived=bare), Alert.HOPPER_DISCONNECTED) is False
    seen = DerivedState(hopper_connected=False, sightings={Capability.HOPPER: Evidence.DISPENSE})
    assert _truth(_snap(derived=seen), Alert.HOPPER_DISCONNECTED) is True


def test_no_visit_counts_hours_since_the_last_one_and_waits_for_a_first() -> None:
    assert _truth(_snap(), Alert.NO_VISIT) is None
    quiet = DerivedState(last_cat_visit=T0 - timedelta(hours=25))
    raw = conditions(_snap(derived=quiet), SETTINGS, T0)
    assert raw[Alert.NO_VISIT] == (True, {"hours": 25, "last_visit": quiet.last_cat_visit.isoformat()})


def test_maintenance_is_due_only_once_a_date_has_been_recorded() -> None:
    snap = Snapshot(robot=None, derived=DerivedState(), online=True,
                    maintenance={"deep_clean": date(2026, 8, 1), "filter": None})
    raw = conditions(snap, SETTINGS, T0)
    assert raw[Alert.DEEP_CLEAN_DUE][0] is True
    assert raw[Alert.DEEP_CLEAN_DUE][1]["due"] == "2026-10-30"
    assert raw[Alert.FILTER_DUE][0] is False
    assert raw[Alert.GLOBE_CLEAN_DUE][0] is False


def test_a_due_date_follows_the_users_calendar_not_utcs() -> None:
    """At 5 pm on the 29th in California it is already the 30th in UTC."""
    snap = Snapshot(robot=None, derived=DerivedState(), online=True,
                    maintenance={"deep_clean": date(2026, 8, 1)}, today=date(2026, 10, 29))
    assert conditions(snap, SETTINGS, T0)[Alert.DEEP_CLEAN_DUE][0] is False


def test_no_robot_document_yet_leaves_every_robot_condition_unknown() -> None:
    raw = conditions(Snapshot(robot=None, derived=DerivedState(), online=True), SETTINGS, T0)
    assert raw[Alert.DRAWER_FULL][0] is None
    assert raw[Alert.OFFLINE][0] is False


# --- the tracker ----------------------------------------------------------------
def test_a_held_condition_waits_out_its_hold_and_is_raised_once() -> None:
    tracker = AlertTracker()
    raw = {Alert.BONNET_REMOVED: (True, {})}
    assert tracker.update(raw, T0) == []
    assert tracker.update(raw, T0 + HOLD[Alert.BONNET_REMOVED] - timedelta(seconds=1)) == []
    raised = tracker.update(raw, T0 + HOLD[Alert.BONNET_REMOVED])
    assert [(t.alert, t.raised) for t in raised] == [(Alert.BONNET_REMOVED, True)]
    assert tracker.update(raw, T0 + timedelta(hours=1)) == []


def test_a_condition_that_clears_inside_its_hold_is_never_raised() -> None:
    tracker = AlertTracker()
    tracker.update({Alert.BONNET_REMOVED: (True, {})}, T0)
    assert tracker.update({Alert.BONNET_REMOVED: (False, {})}, T0 + timedelta(minutes=2)) == []
    assert tracker.update({Alert.BONNET_REMOVED: (True, {})}, T0 + timedelta(minutes=6)) == []


def test_unknown_leaves_an_active_alert_standing_and_false_clears_it() -> None:
    tracker = AlertTracker()
    tracker.update({Alert.DRAWER_FULL: (True, {})}, T0)
    assert tracker.update({Alert.DRAWER_FULL: (None, {})}, T0) == []
    cleared = tracker.update({Alert.DRAWER_FULL: (False, {})}, T0)
    assert [(t.alert, t.raised) for t in cleared] == [(Alert.DRAWER_FULL, False)]


def test_an_alert_carried_over_a_restart_is_not_announced_again() -> None:
    tracker = AlertTracker(active={Alert.DRAWER_FULL})
    assert tracker.update({Alert.DRAWER_FULL: (True, {})}, T0) == []


def test_only_stopped_or_unreachable_robots_are_urgent() -> None:
    assert Alert.OFFLINE in URGENT
    assert Alert.DRAWER_FULL not in URGENT
    assert Alert.DEEP_CLEAN_DUE not in URGENT


# --- moments ----------------------------------------------------------------------
def _visit(at: int, seconds: int = 30) -> VisitEnded:
    end = T0 + timedelta(seconds=at)
    return VisitEnded(started=end - timedelta(seconds=seconds), ended=end)


def test_every_visit_is_a_moment_and_a_long_one_is_two() -> None:
    moments = MomentTracker()
    assert [m.alert for m in moments.visit(_visit(0), 9.4, SETTINGS)] == [Alert.VISIT]
    long = moments.visit(_visit(3600, seconds=400), None, SETTINGS)
    assert [m.alert for m in long] == [Alert.VISIT, Alert.LONG_VISIT]


def test_a_burst_of_visits_pages_once_per_burst() -> None:
    moments = MomentTracker()
    alerts = [
        [m.alert for m in moments.visit(_visit(i * 60), None, SETTINGS)] for i in range(10)
    ]
    assert sum(Alert.FREQUENT_VISITS in a for a in alerts) == 2
    # Visits more than an hour old drop out of the count.
    spaced = MomentTracker()
    for i in range(6):
        assert Alert.FREQUENT_VISITS not in [
            m.alert for m in spaced.visit(_visit(i * 1000), None, SETTINGS)
        ]


def test_a_weight_far_from_the_usual_is_flagged_once_there_is_a_usual() -> None:
    moments = MomentTracker()
    for weight in (10.0, 10.2):
        assert all(m.alert is not Alert.WEIGHT_CHANGE for m in moments.visit(_visit(0), weight, SETTINGS))
    moments.visit(_visit(5000), 9.9, SETTINGS)
    flagged = [m for m in moments.visit(_visit(9000), 8.5, SETTINGS) if m.alert is Alert.WEIGHT_CHANGE]
    assert flagged[0].details == {"weight_lb": 8.5, "usual_lb": 10.0, "change_percent": -15}
    assert len(moments.weights) == 4
    for _ in range(12):
        moments.visit(_visit(20000), 10.0, SETTINGS)
    assert len(moments.weights) == 10


def test_a_cycle_moment_carries_the_count_and_drawer() -> None:
    moment = MomentTracker().cycle(CleanCycleCompleted(1285), 41)
    assert moment.details == {"cycle_count": 1285, "waste_drawer_level": 41}
    assert describe(moment.alert, None, moment.details) == "Clean cycle finished. Drawer 41% full."


def test_a_lock_change_is_a_moment_but_the_first_reading_is_not() -> None:
    moments = MomentTracker()
    assert moments.lock(False) is None
    assert moments.lock(None) is None
    assert moments.lock(False) is None
    changed = moments.lock(True)
    assert changed is not None and changed.details == {"locked": True}


# --- wording ----------------------------------------------------------------------
def test_every_alert_has_words_for_raising_and_clearing() -> None:
    details = {"level": 85, "hours": 25, "visits": 6, "duration_s": 75, "weight_lb": 9.4,
               "change_percent": -12, "usual_lb": 10.6, "locked": False, "cause": "nope"}
    for alert in Alert:
        assert describe(alert, True, details)
        assert describe(alert, False, details)
    assert describe(Alert.VISIT, None, {"duration_s": 75, "weight_lb": 9.4}) == "Cat visit: 1 min 15 s, 9.4 lb."
    assert describe(Alert.LONG_VISIT, None, {"duration_s": 40, "weight_lb": None}) == "Long visit: 40 s."
    assert describe(Alert.GLOBE_FAULT, True, {}) == "Globe motor fault. Check the robot."
    assert describe(Alert.OFFLINE, False, {}) == "Back online."
    assert describe(Alert.CYCLE_COMPLETED, None, {"waste_drawer_level": None}) == "Clean cycle finished."


# --- reminders ------------------------------------------------------------------
LA = ZoneInfo("America/Los_Angeles")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A Los Angeles wall-clock time on a November 2026 day, as UTC."""
    return datetime(2026, 11, day, hour, minute, tzinfo=LA).astimezone(UTC)


def _true(*alerts: Alert) -> dict:
    return {alert: (True, {}) for alert in alerts}


def test_an_urgent_alert_is_reminded_every_six_hours_until_it_clears() -> None:
    reminders = Reminders()
    reminders.track({Alert.GLOBE_FAULT}, _at(2, 9))
    current = _true(Alert.GLOBE_FAULT)
    assert reminders.due(SETTINGS, _at(2, 14, 59), LA, current) == []
    assert reminders.due(SETTINGS, _at(2, 15), LA, current) == [Alert.GLOBE_FAULT]
    assert reminders.due(SETTINGS, _at(2, 16), LA, current) == []
    assert reminders.due(SETTINGS, _at(2, 21), LA, current) == [Alert.GLOBE_FAULT]
    reminders.track(set(), _at(2, 22))
    assert reminders.since == reminders.reminded == {}


def test_other_alerts_are_reminded_at_seven_and_nineteen_once_six_hours_old() -> None:
    reminders = Reminders()
    reminders.track({Alert.LITTER_LOW}, _at(2, 18, 55))
    current = _true(Alert.LITTER_LOW)
    # Five minutes old at 19:00: the first notice is still fresh.
    assert reminders.due(SETTINGS, _at(2, 19), LA, current) == []
    assert reminders.due(SETTINGS, _at(3, 1), LA, current) == []
    assert reminders.due(SETTINGS, _at(3, 7), LA, current) == [Alert.LITTER_LOW]
    assert reminders.due(SETTINGS, _at(3, 7, 1), LA, current) == []
    assert reminders.due(SETTINGS, _at(3, 19, 1), LA, current) == [Alert.LITTER_LOW]


def test_a_set_time_missed_by_over_an_hour_is_skipped_not_sent_late() -> None:
    reminders = Reminders()
    reminders.track({Alert.DRAWER_FULL}, _at(2, 6))
    assert reminders.due(SETTINGS, _at(2, 20, 30), LA, _true(Alert.DRAWER_FULL)) == []


def test_reminders_skip_what_cannot_be_checked_and_honour_zero() -> None:
    reminders = Reminders()
    reminders.track({Alert.DRAWER_FULL, Alert.OFFLINE}, _at(2, 0))
    current = {Alert.DRAWER_FULL: (None, {}), Alert.OFFLINE: (True, {})}
    off = AlertSettings(urgent_reminder_hours=0)
    assert reminders.due(off, _at(2, 7), LA, current) == []
    assert reminders.due(SETTINGS, _at(2, 7), LA, current) == [Alert.OFFLINE]


def test_set_times_follow_the_wall_clock_across_the_dst_change() -> None:
    """1 November 2026 is the fall-back day: 19:00 local is 03:00 UTC, not 02:00."""
    reminders = Reminders()
    reminders.track({Alert.FILTER_DUE}, _at(1, 8))
    current = _true(Alert.FILTER_DUE)
    assert reminders.due(SETTINGS, datetime(2026, 11, 2, 2, 30, tzinfo=UTC), LA, current) == []
    assert reminders.due(SETTINGS, datetime(2026, 11, 2, 3, 0, tzinfo=UTC), LA, current) == [
        Alert.FILTER_DUE
    ]


def test_a_silenced_phone_is_remembered_until_the_alert_clears() -> None:
    reminders = Reminders()
    assert reminders.silence(Alert.DRAWER_FULL, "phone-a") is False
    reminders.track({Alert.DRAWER_FULL}, T0)
    assert reminders.silence(Alert.DRAWER_FULL, "phone-a") is True
    assert reminders.silenced == {Alert.DRAWER_FULL: {"phone-a"}}
    reminders.track(set(), T0)
    assert reminders.silenced == {}
