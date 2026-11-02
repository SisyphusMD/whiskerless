"""Announce each alert as one ``whiskerless_alert`` event on Home Assistant's bus.

The rules for WHEN live in the library (``alerts``); this is only the plumbing: feed
it the robot as Home Assistant sees it, re-check every minute so hold times and due
dates elapse with no new message, and fire one event per change. The notification
blueprint listens for these, and so can any automation.

What is active is kept on the entry, so a restart does not announce a drawer that
was already full before it, and so are the reminder clocks and who silenced what.
The Silence button on a notification comes back as the Companion app's own action
event, which is heard here directly rather than through an action of our own. Nothing is evaluated until Home Assistant has started:
an alert raised before the automations are armed would be recorded as announced
while nobody heard it.
"""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from whiskerless.devices.litter_robot_4.alerts import (
    HOLD,
    URGENT,
    Alert,
    AlertSettings,
    AlertTracker,
    Moment,
    MomentTracker,
    Reminders,
    Snapshot,
    Transition,
    conditions,
    describe,
)
from whiskerless.devices.litter_robot_4.derive import CleanCycleCompleted, VisitEnded

from .const import (
    CONF_ACTIVE_ALERTS,
    CONF_ALERT_SETTINGS,
    CONF_LAST_VISIT,
    CONF_REMINDERS,
    CONF_SERIAL,
    CONF_WEIGHT_HISTORY,
    DEFAULT_NAME,
    DOMAIN,
    EVENT_ALERT,
    EVENT_NOTIFICATION_ACTION,
    SIGNAL_CAT_VISIT,
    SIGNAL_CLEAN_CYCLE,
    SILENCE_ACTION,
)
from .coordinator import WhiskerlessCoordinator

_TICK = timedelta(minutes=1)
_SETUP_FAILURES = f"{DOMAIN}_setup_failures"
# Settings where 0 means something (no urgent reminders, a midnight reminder);
# for every other threshold a 0 can only be a stored value that no longer fits.
_MAY_BE_ZERO = {"urgent_reminder_hours", "morning_reminder_hour", "evening_reminder_hour"}
_MAINTENANCE_KEYS = {
    "deep_clean": "last_deep_clean",
    "filter": "last_filter_change",
    "globe_clean": "last_globe_clean",
}


def alert_settings(options: dict[str, Any]) -> AlertSettings:
    """The user's thresholds, ignoring anything stored that no longer fits."""
    stored = options.get(CONF_ALERT_SETTINGS) or {}
    known = {f.name for f in fields(AlertSettings)}
    values: dict[str, int] = {}
    for name, value in stored.items():
        floor = 0 if name in _MAY_BE_ZERO else 1
        if name in known and isinstance(value, (int, float)) and value >= floor:
            values[name] = int(value)
    return AlertSettings(**values)


@callback
def async_report_setup_failure(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Keep the offline hold for a robot that cannot be reached at setup.

    A failed setup leaves no coordinator and no publisher, and Home Assistant retries
    it every minute or so for as long as the robot stays away. Without this, a robot
    that was off when Home Assistant started would never be reported offline. The
    publisher that finally starts finds ``offline`` active and says "Back online".
    """
    now = dt_util.utcnow()
    since: datetime = hass.data.setdefault(_SETUP_FAILURES, {}).setdefault(entry.entry_id, now)
    active = list(entry.options.get(CONF_ACTIVE_ALERTS) or [])
    if Alert.OFFLINE.value in active or now - since < HOLD[Alert.OFFLINE]:
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ACTIVE_ALERTS: sorted([*active, Alert.OFFLINE.value])}
    )
    _fire(
        hass,
        entry.data[CONF_SERIAL],
        entry.data.get(CONF_NAME) or DEFAULT_NAME,
        Alert.OFFLINE,
        "raised",
        describe(Alert.OFFLINE, True, {}),
        {},
    )


@callback
def async_clear_setup_failure(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the failed-setup clock once the robot has answered."""
    hass.data.get(_SETUP_FAILURES, {}).pop(entry.entry_id, None)


def _fire(
    hass: HomeAssistant,
    serial: str,
    name: str,
    alert: Alert,
    kind: str,
    message: str,
    details: dict[str, Any],
    silenced: list[str] | None = None,
) -> None:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, serial)})
    hass.bus.async_fire(
        EVENT_ALERT,
        {
            "device_id": device.id if device else None,
            "serial": serial,
            # The name the user sees, including a rename made in the UI.
            "robot": (device.name_by_user or device.name) if device else name,
            "alert": alert.value,
            "event": kind,
            "urgent": alert in URGENT,
            "message": message,
            "details": details,
            # Phones that asked not to be reminded; only a reminder carries any.
            "silenced": silenced or [],
        },
    )


class AlertPublisher:
    """One robot's alerts, from its coordinator to the event bus."""

    def __init__(self, hass: HomeAssistant, coordinator: WhiskerlessCoordinator) -> None:
        self._hass = hass
        self._coordinator = coordinator
        options = coordinator.config_entry.options
        active = {a for a in Alert if a.value in (options.get(CONF_ACTIVE_ALERTS) or [])}
        self._tracker = AlertTracker(active=active)
        weights = [
            float(w) for w in options.get(CONF_WEIGHT_HISTORY) or [] if isinstance(w, (int, float))
        ]
        self._moments = MomentTracker(weights=weights)
        self._reminders = _restore_reminders(options.get(CONF_REMINDERS), active)
        # The coordinator forgets the last visit across a restart, and "no visit for a
        # day" matters most exactly when none arrives to remind it.
        self._last_visit = dt_util.parse_datetime(str(options.get(CONF_LAST_VISIT) or ""))

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Begin evaluating once Home Assistant has started; the returned callable stops it."""
        unsubscribe: list[CALLBACK_TYPE] = []

        @callback
        def begin(_hass: HomeAssistant) -> None:
            serial = self._coordinator.serial
            unsubscribe.extend(
                [
                    self._coordinator.async_add_listener(self._evaluate),
                    async_track_time_interval(self._hass, self._tick, _TICK),
                    async_dispatcher_connect(
                        self._hass, SIGNAL_CAT_VISIT.format(serial), self._visit
                    ),
                    async_dispatcher_connect(
                        self._hass, SIGNAL_CLEAN_CYCLE.format(serial), self._cycle
                    ),
                    self._hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, self._action),
                ]
            )
            self._evaluate()

        unsubscribe.append(async_at_started(self._hass, begin))

        @callback
        def stop() -> None:
            for unsub in unsubscribe:
                unsub()

        return stop

    @callback
    def _tick(self, _now: object) -> None:
        self._evaluate()

    @callback
    def _evaluate(self) -> None:
        coordinator = self._coordinator
        data = coordinator.data
        derived = data.derived
        if self._last_visit and (
            derived.last_cat_visit is None or derived.last_cat_visit < self._last_visit
        ):
            derived = replace(derived, last_cat_visit=self._last_visit)
        snapshot = Snapshot(
            robot=data.robot,
            derived=derived,
            online=coordinator.last_update_success,
            litter_percent=data.litter_percent,
            maintenance={
                key: coordinator.maintenance_date(option)
                for key, option in _MAINTENANCE_KEYS.items()
            },
            # The user's midnight, not UTC's, is when a maintenance date falls due.
            today=dt_util.now().date(),
        )
        settings = alert_settings(dict(coordinator.config_entry.options))
        now = dt_util.utcnow()
        raw = conditions(snapshot, settings, now, self._tracker.active)
        transitions = self._tracker.update(raw, now)
        if coordinator.last_update_success:
            lock = self._moments.lock(data.robot.keypad_lockout)
            if lock is not None:
                self._fire_moment(lock)
        self._reminders.track(self._tracker.active, now)
        due = self._reminders.due(settings, now, dt_util.get_default_time_zone(), raw)
        # Compared, not keyed on a change: a clock started at an upgrade has no
        # transition behind it, and unsaved it would restart with every reload.
        stored = self._stored_reminders()
        options = coordinator.config_entry.options
        if transitions or stored != options.get(CONF_REMINDERS):
            self._save(
                {
                    CONF_ACTIVE_ALERTS: sorted(a.value for a in self._tracker.active),
                    CONF_REMINDERS: stored,
                }
            )
        for transition in transitions:
            self._fire_transition(transition)
        for alert in due:
            details = raw[alert][1]
            self._fire(
                alert,
                "reminder",
                f"Reminder: {describe(alert, True, details)}",
                details,
                sorted(self._reminders.silenced.get(alert, set())),
            )

    @callback
    def _action(self, event: Event) -> None:
        """A Silence button tapped on a phone, for one of this robot's alerts."""
        parts = str(event.data.get("action") or "").split("|")
        if len(parts) != 4 or parts[0] != SILENCE_ACTION or parts[1] != self._coordinator.serial:
            return
        _, _, alert_key, phone = parts
        alert = next((a for a in Alert if a.value == alert_key), None)
        if alert is not None and self._reminders.silence(alert, phone):
            self._save({CONF_REMINDERS: self._stored_reminders()})

    def _stored_reminders(self) -> dict[str, dict[str, Any]]:
        reminders = self._reminders
        return {
            alert.value: {
                "since": since.isoformat(),
                "reminded": reminded.isoformat() if (reminded := reminders.reminded.get(alert)) else None,
                "silenced": sorted(reminders.silenced.get(alert, set())),
            }
            for alert, since in reminders.since.items()
        }

    @callback
    def _visit(self, visit: VisitEnded, weight_lb: float | None) -> None:
        settings = alert_settings(dict(self._coordinator.config_entry.options))
        for moment in self._moments.visit(visit, weight_lb, settings):
            self._fire_moment(moment)
        self._last_visit = visit.ended
        self._save(
            {CONF_WEIGHT_HISTORY: self._moments.weights, CONF_LAST_VISIT: visit.ended.isoformat()}
        )

    @callback
    def _cycle(self, cycle: CleanCycleCompleted) -> None:
        drawer = self._coordinator.data.robot.waste_drawer_level
        self._fire_moment(self._moments.cycle(cycle, drawer))

    @callback
    def _save(self, values: dict[str, Any]) -> None:
        entry = self._coordinator.config_entry
        self._hass.config_entries.async_update_entry(entry, options={**entry.options, **values})

    def _fire_transition(self, transition: Transition) -> None:
        self._fire(
            transition.alert,
            "raised" if transition.raised else "cleared",
            describe(transition.alert, transition.raised, transition.details),
            transition.details,
        )

    def _fire_moment(self, moment: Moment) -> None:
        self._fire(moment.alert, "moment", describe(moment.alert, None, moment.details), moment.details)

    def _fire(
        self,
        alert: Alert,
        kind: str,
        message: str,
        details: dict[str, Any],
        silenced: list[str] | None = None,
    ) -> None:
        coordinator = self._coordinator
        _fire(
            self._hass, coordinator.serial, coordinator.device_name, alert, kind, message,
            details, silenced,
        )


def _restore_reminders(stored: object, active: set[Alert]) -> Reminders:
    """The reminder clocks as saved, for alerts still active.

    An alert active from before reminders existed has no clock; it starts now, so an
    upgrade postpones its first reminder rather than sending a burst of them.
    """
    reminders = Reminders()
    saved = stored if isinstance(stored, dict) else {}
    now = dt_util.utcnow()
    for alert in active:
        entry = saved.get(alert.value)
        entry = entry if isinstance(entry, dict) else {}
        reminders.since[alert] = dt_util.parse_datetime(str(entry.get("since") or "")) or now
        if reminded := dt_util.parse_datetime(str(entry.get("reminded") or "")):
            reminders.reminded[alert] = reminded
        phones = entry.get("silenced")
        if isinstance(phones, list) and phones:
            reminders.silenced[alert] = {str(p) for p in phones}
    return reminders
