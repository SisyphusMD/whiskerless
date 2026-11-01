"""Which of the Whisker app's notifications are true now, and which moments deserve one.

Going local loses every push the Whisker app sent. This module decides WHEN each one
should fire; delivering it (which phone, quiet hours, wording on the lock screen) is
the consumer's business. Pure: callers pass in what they know and the time, so every
rule is testable without a broker or a clock.

Two kinds of alert:

* **Conditions** have a start and an end (drawer full, a fault, offline). The
  :class:`AlertTracker` turns raw truth into ``raised``/``cleared`` transitions,
  applying hold times so a bonnet lifted for a quick scoop never pages anyone.
* **Moments** have no end (a visit, a finished cycle). :class:`MomentTracker`
  turns the reducer's effects into them.

The catalog follows the Whisker LR4 support articles, which say per fault that the
app sends a push. Faults this firmware does not publish locally (laser board, dirty
sensor, motion in drawer) are absent rather than guessed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from statistics import median
from typing import Any

from .const import GLOBE_MOTOR_FAULT_CAUSES, LITTER_UNRELIABLE_STATUSES
from .derive import (
    Capability,
    CleanCycleCompleted,
    DerivedState,
    VisitEnded,
    globe_motor_faulted,
    hopper_empty,
)
from .derive import excess_weight as derive_excess_weight
from .models import LitterRobot4State

__all__ = [
    "HOLD",
    "URGENT",
    "Alert",
    "AlertSettings",
    "AlertTracker",
    "Moment",
    "MomentTracker",
    "Snapshot",
    "Transition",
    "conditions",
    "describe",
]


class Alert(StrEnum):
    """Every alert, by the stable key consumers filter on."""

    # Faults
    GLOBE_FAULT = "globe_fault"
    BONNET_REMOVED = "bonnet_removed"
    DRAWER_FULL_LOCKOUT = "drawer_full_lockout"
    CAT_SENSOR_BLOCKED = "cat_sensor_blocked"
    EXCESS_WEIGHT = "excess_weight"
    STUCK_CYCLE = "stuck_cycle"
    OFFLINE = "offline"
    # Drawer and litter
    DRAWER_FULL = "drawer_full"
    DRAWER_LEVEL = "drawer_level"
    LITTER_LOW = "litter_low"
    HOPPER_EMPTY = "hopper_empty"
    HOPPER_DISCONNECTED = "hopper_disconnected"
    # Cat health (moments, except no_visit)
    NO_VISIT = "no_visit"
    FREQUENT_VISITS = "frequent_visits"
    LONG_VISIT = "long_visit"
    WEIGHT_CHANGE = "weight_change"
    VISIT = "visit"
    # Maintenance
    DEEP_CLEAN_DUE = "deep_clean_due"
    FILTER_DUE = "filter_due"
    GLOBE_CLEAN_DUE = "globe_clean_due"
    # Activity (moments)
    CYCLE_COMPLETED = "cycle_completed"
    PANEL_LOCK_CHANGED = "panel_lock_changed"


#: Worth breaking through Focus for: the robot has stopped, or cannot be reached.
URGENT: frozenset[Alert] = frozenset(
    {
        Alert.GLOBE_FAULT,
        Alert.BONNET_REMOVED,
        Alert.DRAWER_FULL_LOCKOUT,
        Alert.CAT_SENSOR_BLOCKED,
        Alert.EXCESS_WEIGHT,
        Alert.STUCK_CYCLE,
        Alert.OFFLINE,
    }
)

#: How long a condition must hold before it is raised. A bonnet lifted to scoop, a
#: cat sitting a while, a heartbeat missed in passing: none of those is news.
#: Excess weight needs none here, because the reducer's rule already waits 30 min.
HOLD: dict[Alert, timedelta] = {
    Alert.BONNET_REMOVED: timedelta(minutes=5),
    Alert.CAT_SENSOR_BLOCKED: timedelta(minutes=30),
    # A clean cycle takes minutes; a paused one holds status 10 indefinitely (one
    # captured pause ran 10.4 h), so status 10 for half an hour is a stuck cycle.
    Alert.STUCK_CYCLE: timedelta(minutes=30),
    Alert.OFFLINE: timedelta(minutes=15),
}


@dataclass(frozen=True, slots=True)
class AlertSettings:
    """The thresholds a user can change. Defaults follow Whisker where it says."""

    drawer_level_percent: int = 80
    litter_low_percent: int = 30
    no_visit_hours: int = 24
    long_visit_minutes: int = 5
    frequent_visits_per_hour: int = 5
    weight_change_percent: int = 10
    #: Whisker: deep clean at least every 3 months, a new carbon filter monthly,
    #: and a basic globe clean every 1-3 months.
    deep_clean_days: int = 90
    filter_days: int = 30
    globe_clean_days: int = 60


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What a consumer knows about one robot at one moment."""

    robot: LitterRobot4State | None
    derived: DerivedState
    online: bool
    #: Litter %, as the consumer presents it (it owns the calibration).
    litter_percent: int | None = None
    #: Last-done dates keyed ``deep_clean``, ``filter`` and ``globe_clean``.
    maintenance: Mapping[str, date | None] = field(default_factory=dict)
    #: The user's calendar date, for maintenance due dates. Elapsed times use the
    #: UTC ``now``: two datetimes sharing a zone subtract by wall clock, which is an
    #: hour out across a DST change.
    today: date | None = None


_MAINTENANCE: tuple[tuple[Alert, str, str], ...] = (
    (Alert.DEEP_CLEAN_DUE, "deep_clean", "deep_clean_days"),
    (Alert.FILTER_DUE, "filter", "filter_days"),
    (Alert.GLOBE_CLEAN_DUE, "globe_clean", "globe_clean_days"),
)

#: A condition's truth: True, False, or None for "cannot tell right now", which
#: leaves the alert as it was rather than clearing and re-raising it.
Truth = bool | None


def conditions(
    snap: Snapshot, settings: AlertSettings, now: datetime
) -> dict[Alert, tuple[Truth, dict[str, Any]]]:
    """The raw truth of every condition alert, before hold times."""
    out: dict[Alert, tuple[Truth, dict[str, Any]]] = {
        Alert.OFFLINE: (not snap.online, {}),
    }
    out.update(_maintenance(snap, settings, snap.today or now.date()))
    last_visit = snap.derived.last_cat_visit
    if last_visit is None:
        out[Alert.NO_VISIT] = (None, {})
    else:
        hours = (now - last_visit).total_seconds() / 3600
        out[Alert.NO_VISIT] = (
            hours >= settings.no_visit_hours,
            {"hours": int(hours), "last_visit": last_visit.isoformat()},
        )
    robot = snap.robot
    if robot is None or not snap.online:
        # A robot we cannot hear says nothing new about its drawer or its faults.
        for alert in _ROBOT_CONDITIONS:
            out[alert] = (None, {})
        return out
    derived = snap.derived

    faulted = globe_motor_faulted(derived, robot)
    code = derived.globe_motor_fault or robot.globe_motor_fault
    cause = GLOBE_MOTOR_FAULT_CAUSES.get(code, "unknown") if code else None
    out[Alert.GLOBE_FAULT] = (faulted, {"cause": cause} if cause else {})
    out[Alert.BONNET_REMOVED] = (robot.is_bonnet_removed, {})
    out[Alert.DRAWER_FULL_LOCKOUT] = (robot.drawer_full_lockout, {})
    out[Alert.CAT_SENSOR_BLOCKED] = (robot.cat_detected, {})
    out[Alert.EXCESS_WEIGHT] = (derive_excess_weight(derived, robot, now), {})
    out[Alert.STUCK_CYCLE] = (
        None if robot.robot_status is None else robot.robot_status == "clean_cycle",
        {},
    )
    out[Alert.DRAWER_FULL] = (robot.is_dfi_full, {})
    level = robot.waste_drawer_level
    # A Reset zeroes the gauge before anything is measured: that zero is not news.
    if level is None or robot.is_dfi_reset_pending:
        out[Alert.DRAWER_LEVEL] = (None, {})
    else:
        out[Alert.DRAWER_LEVEL] = (level >= settings.drawer_level_percent, {"level": level})
    litter = snap.litter_percent
    # The distance sensor looks at the globe, not the litter, while it turns.
    if litter is None or robot.robot_status in LITTER_UNRELIABLE_STATUSES:
        out[Alert.LITTER_LOW] = (None, {})
    else:
        out[Alert.LITTER_LOW] = (litter <= settings.litter_low_percent, {"level": litter})
    if derived.sighted(Capability.HOPPER):
        out[Alert.HOPPER_EMPTY] = (hopper_empty(derived), {})
        connected = derived.hopper_connected
        out[Alert.HOPPER_DISCONNECTED] = (None if connected is None else not connected, {})
    else:
        out[Alert.HOPPER_EMPTY] = (False, {})
        out[Alert.HOPPER_DISCONNECTED] = (False, {})
    return out


_ROBOT_CONDITIONS: tuple[Alert, ...] = (
    Alert.GLOBE_FAULT,
    Alert.BONNET_REMOVED,
    Alert.DRAWER_FULL_LOCKOUT,
    Alert.CAT_SENSOR_BLOCKED,
    Alert.EXCESS_WEIGHT,
    Alert.STUCK_CYCLE,
    Alert.DRAWER_FULL,
    Alert.DRAWER_LEVEL,
    Alert.LITTER_LOW,
    Alert.HOPPER_EMPTY,
    Alert.HOPPER_DISCONNECTED,
)


def _maintenance(
    snap: Snapshot, settings: AlertSettings, today: date
) -> dict[Alert, tuple[Truth, dict[str, Any]]]:
    out: dict[Alert, tuple[Truth, dict[str, Any]]] = {}
    for alert, key, setting in _MAINTENANCE:
        last = snap.maintenance.get(key)
        if last is None:
            # Never recorded means the user is not tracking it, not that it is due.
            out[alert] = (False, {})
            continue
        due = last + timedelta(days=getattr(settings, setting))
        out[alert] = (today >= due, {"last_done": last.isoformat(), "due": due.isoformat()})
    return out


@dataclass(frozen=True, slots=True)
class Transition:
    """A condition alert started or ended."""

    alert: Alert
    raised: bool
    details: dict[str, Any]


@dataclass
class AlertTracker:
    """Turns raw condition truth into transitions, applying :data:`HOLD`.

    ``active`` is the one thing a consumer should persist: an alert still true
    after a restart is then not announced a second time.
    """

    active: set[Alert] = field(default_factory=set)
    _since: dict[Alert, datetime] = field(default_factory=dict)

    def update(
        self, raw: Mapping[Alert, tuple[Truth, dict[str, Any]]], now: datetime
    ) -> list[Transition]:
        out: list[Transition] = []
        for alert, (truth, details) in raw.items():
            if truth is None:
                continue
            if not truth:
                self._since.pop(alert, None)
                if alert in self.active:
                    self.active.discard(alert)
                    out.append(Transition(alert, False, details))
                continue
            if alert in self.active:
                continue
            since = self._since.setdefault(alert, now)
            if now - since >= HOLD.get(alert, timedelta(0)):
                self.active.add(alert)
                out.append(Transition(alert, True, details))
        return out


@dataclass(frozen=True, slots=True)
class Moment:
    """Something that happened, with no end to wait for."""

    alert: Alert
    details: dict[str, Any]


@dataclass
class MomentTracker:
    """Turns visits, cycles and lock changes into moments.

    ``weights`` is worth persisting, so the weight-change rule has a baseline from
    the first visit after a restart. It mixes every cat that uses the robot, which
    is why that alert ships off: in a two-cat home the median is nobody's weight.
    """

    weights: list[float] = field(default_factory=list)
    _visits: deque[datetime] = field(default_factory=deque)
    _lock: bool | None = None

    def visit(
        self, visit: VisitEnded, weight_lb: float | None, settings: AlertSettings
    ) -> list[Moment]:
        details: dict[str, Any] = {"duration_s": visit.duration_s, "weight_lb": weight_lb}
        out = [Moment(Alert.VISIT, details)]
        if visit.duration_s >= settings.long_visit_minutes * 60:
            out.append(Moment(Alert.LONG_VISIT, details))
        self._visits.append(visit.ended)
        hour_ago = visit.ended - timedelta(hours=1)
        while self._visits and self._visits[0] < hour_ago:
            self._visits.popleft()
        if len(self._visits) >= settings.frequent_visits_per_hour:
            out.append(Moment(Alert.FREQUENT_VISITS, {"visits": len(self._visits)}))
            # One page per burst, not one per visit inside it.
            self._visits.clear()
        if weight_lb is not None:
            if len(self.weights) >= 3:
                usual = median(self.weights)
                change = (weight_lb - usual) / usual * 100
                if abs(change) >= settings.weight_change_percent:
                    out.append(
                        Moment(
                            Alert.WEIGHT_CHANGE,
                            {"weight_lb": weight_lb, "usual_lb": round(usual, 1),
                             "change_percent": round(change)},
                        )
                    )
            self.weights = [*self.weights, weight_lb][-10:]
        return out

    def cycle(self, cycle: CleanCycleCompleted, drawer_level: int | None) -> Moment:
        return Moment(
            Alert.CYCLE_COMPLETED, {"cycle_count": cycle.count, "waste_drawer_level": drawer_level}
        )

    def lock(self, locked: bool | None) -> Moment | None:
        """A change of Control lock, but never the first reading of a session."""
        previous, self._lock = self._lock, (locked if locked is not None else self._lock)
        if previous is None or locked is None or locked == previous:
            return None
        return Moment(Alert.PANEL_LOCK_CHANGED, {"locked": locked})


_CAUSE_TEXT = {
    "timeout": "the globe did not reach its position in time",
    "motor_disconnected": "the motor is disconnected",
    "under_voltage": "the supply voltage is low — check the power adapter",
    "over_current": "the motor is straining, possibly jammed",
    "current_spike": "the motor is straining, possibly jammed",
    "pinch": "a pinch was detected",
    "all_sensors": "every sensor reported a fault",
}


def describe(alert: Alert, raised: bool | None, details: Mapping[str, Any]) -> str:
    """One plain English line for a notification. ``raised`` is None for a moment."""
    if raised is False:
        return _CLEARED.get(alert, "Back to normal.")
    if alert is Alert.GLOBE_FAULT:
        cause = _CAUSE_TEXT.get(str(details.get("cause")))
        return f"Globe motor fault: {cause}." if cause else "Globe motor fault. Check the robot."
    if alert is Alert.DRAWER_LEVEL:
        return f"Waste drawer is {details.get('level')}% full."
    if alert is Alert.LITTER_LOW:
        return f"Litter is low ({details.get('level')}%). Add litter."
    if alert is Alert.NO_VISIT:
        return f"No cat visit in {details.get('hours')} hours."
    if alert is Alert.FREQUENT_VISITS:
        return f"{details.get('visits')} visits in the last hour."
    if alert in (Alert.VISIT, Alert.LONG_VISIT):
        minutes, seconds = divmod(int(details.get("duration_s") or 0), 60)
        length = f"{minutes} min {seconds} s" if minutes else f"{seconds} s"
        weight = details.get("weight_lb")
        prefix = "Long visit" if alert is Alert.LONG_VISIT else "Cat visit"
        return f"{prefix}: {length}" + (f", {weight} lb." if weight is not None else ".")
    if alert is Alert.WEIGHT_CHANGE:
        return (
            f"Weighed {details.get('weight_lb')} lb, {details.get('change_percent'):+}% "
            f"from the usual {details.get('usual_lb')} lb."
        )
    if alert is Alert.CYCLE_COMPLETED:
        level = details.get("waste_drawer_level")
        return "Clean cycle finished." + (f" Drawer {level}% full." if level is not None else "")
    if alert is Alert.PANEL_LOCK_CHANGED:
        return "Control lock turned on." if details.get("locked") else "Control lock turned off."
    return _RAISED[alert]


_RAISED: dict[Alert, str] = {
    Alert.BONNET_REMOVED: "The bonnet has been off for 5 minutes. The robot will not cycle.",
    Alert.DRAWER_FULL_LOCKOUT: "Stopped: the drawer is full. Empty it and press Reset.",
    Alert.CAT_SENSOR_BLOCKED: "The cat sensor has been blocked for 30 minutes.",
    Alert.EXCESS_WEIGHT: "Something has been on the scale for 30 minutes. The robot will not cycle.",
    Alert.STUCK_CYCLE: "A clean cycle has been stuck for 30 minutes.",
    Alert.OFFLINE: "Not responding for 15 minutes.",
    Alert.DRAWER_FULL: "Waste drawer full. Empty it and press Reset.",
    Alert.HOPPER_EMPTY: "The hopper is out of litter.",
    Alert.HOPPER_DISCONNECTED: "The hopper is disconnected.",
    Alert.DEEP_CLEAN_DUE: "A deep clean is due.",
    Alert.FILTER_DUE: "Time for a new carbon filter.",
    Alert.GLOBE_CLEAN_DUE: "A globe clean is due.",
}

_CLEARED: dict[Alert, str] = {
    Alert.OFFLINE: "Back online.",
    Alert.GLOBE_FAULT: "Globe motor fault cleared.",
    Alert.DRAWER_FULL: "Waste drawer emptied.",
    Alert.DRAWER_FULL_LOCKOUT: "Running again.",
    Alert.BONNET_REMOVED: "Bonnet back on.",
}
