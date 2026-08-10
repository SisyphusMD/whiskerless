"""Coordinator for the Whiskerless integration.

Rides on Home Assistant's own MQTT integration: it subscribes to one robot's
topics through HA's shared broker connection, decodes pushed state, and serves it
to entities. A long heartbeat re-requests state to notice an unresponsive robot;
writes publish then read back the value (the firmware commits some registers with
a delay). Every command passes the library's safety guard before going on the wire.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_4 import (
    LitterRobot4State,
    commands,
    every_weekday_is,
    weekday_sleep_days_match,
)
from whiskerless.devices.litter_robot_4 import const as lr4
from whiskerless.devices.litter_robot_4.calibration import (
    HOPPER_CORROBORATION,
    HOPPER_PLAUSIBLE,
    LITTER_CORROBORATION_MM,
    LITTER_MAX_SPAN_MM,
    LITTER_PLAUSIBLE_MM,
    Learned,
    hopper_percent,
    litter_is_sampleable,
)
from whiskerless.devices.litter_robot_4.commands import Command
from whiskerless.devices.litter_robot_4.const import command_topic, subscribe_topic
from whiskerless.devices.litter_robot_4.events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayMoved,
    HopperDispensed,
    HopperLinkChanged,
    events_from_readings,
)
from whiskerless.devices.litter_robot_4.protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)
from whiskerless.safety import assert_sendable

from .const import (
    CONF_HOPPER_LAST,
    CONF_HOPPER_SEEN,
    CONF_LEARNED_HOPPER,
    CONF_LEARNED_LITTER,
    CONF_LITTER_EMPTY_MM,
    CONF_LITTER_FULL_MM,
    CONF_SERIAL,
    DEFAULT_NAME,
    DOMAIN,
    HEARTBEAT_INTERVAL,
    LOGGER,
)

type WhiskerlessConfigEntry = ConfigEntry[WhiskerlessCoordinator]

_STATE_TIMEOUT = 10.0
_VERIFY_TIMEOUT = 8.0
# Gap between the publishes of one logical write. Sending a schedule means seven
# register writes, and two issued back to back were observed landing as one — the
# robot took the first and dropped the second. The retry loop catches that; the
# gap is what stops it happening, and it also keeps the read-back request from
# overtaking the last write and reading pre-write state.
_WRITE_GAP = 0.2
_ACTIVITY_THROTTLE = 2.0
# Two dispense reports closer together than this are the same event redelivered;
# real dispenses are a cycle or more apart.
_DISPENSE_DEDUPE = 60.0
# State documents arrive on a multi-minute cadence, so anything closer than this
# is a redelivery rather than an independent observation.
_STATE_DEDUPE = 30.0
# How long to wait for the robot to echo a panel-button press. The echo is the
# robot's own acknowledgement that it acted, which QoS 1 cannot give — that only
# proves the broker accepted the message.
_PRESS_TIMEOUT = 5.0

@dataclass
class WhiskerlessData:
    """The coordinator's data payload.

    ``robot`` is the latest full-state snapshot. The remaining fields are
    derived from the activity stream, which carries facts the state document
    never does (per-visit cat weight, hopper dispenses, hopper link state).
    """

    robot: LitterRobot4State
    cat_weight_lb: float | None = None
    last_cat_visit: datetime | None = None
    last_visit_duration_s: int | None = None
    hopper_connected: bool | None = None
    # Distinguishes "never heard from the link register" from a reading we
    # heard but cannot name: only the former may fall back to a restored value.
    hopper_link_reported: bool = False
    # Per-robot litter calibration, so the percentage sensor can use it.
    # The pair actually used for the percentage: the user's measurements when
    # they exist, otherwise the learned extremes once they span enough to trust.
    litter_full_mm: int | None = None
    litter_empty_mm: int | None = None
    # What the user measured, for the diagnostic sensor. Deliberately not the
    # learned value: "at the line" is a claim only a person can make.
    litter_reference_mm: int | None = None
    hopper_fill_percent: int | None = None
    last_hopper_dispensed: datetime | None = None
    hopper_fill_raw: int | None = None
    drawer_last_moved: datetime | None = None


class WhiskerlessCoordinator(DataUpdateCoordinator[WhiskerlessData]):
    """Subscribes to one robot via HA's MQTT and pushes its state to entities."""

    config_entry: WhiskerlessConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: WhiskerlessConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=HEARTBEAT_INTERVAL,
        )
        self.serial: str = config_entry.data[CONF_SERIAL]
        self.device_name: str = config_entry.data.get(CONF_NAME) or DEFAULT_NAME
        self._robot: LitterRobot4State | None = None
        self._state_event = asyncio.Event()
        self._io_lock = asyncio.Lock()
        self._last_activity_refresh = 0.0
        self._tasks: set[asyncio.Task[None]] = set()
        # Activity-derived facts (never present in the state document).
        self._cat_weight_lb: float | None = None
        self._last_cat_visit: datetime | None = None
        self._last_visit_duration_s: int | None = None
        self._hopper_connected: bool | None = None
        self._hopper_link_reported = False
        self._hopper_seen = bool(config_entry.options.get(CONF_HOPPER_SEEN))
        self._learned_litter = Learned.from_dict(config_entry.options.get(CONF_LEARNED_LITTER))
        self._learned_hopper = Learned.from_dict(config_entry.options.get(CONF_LEARNED_HOPPER))
        self._last_hopper_dispensed: datetime | None = None
        self._hopper_fill_raw: int | None = None
        self._last_hopper_sample_at = 0.0
        self._last_litter_sample_at = 0.0
        self._drawer_last_moved: datetime | None = None
        self._press_echo = asyncio.Event()
        self._awaited_press: int | None = None
        # Enabling an entity reloads the entry, which builds a fresh coordinator
        # and would otherwise discard the very readings that proved the hopper
        # exists. They are persisted with the flag, so the newly enabled
        # entities have a value the moment they appear.
        last = config_entry.options.get(CONF_HOPPER_LAST) or {}
        if last:
            self._hopper_connected = last.get("connected")
            self._hopper_link_reported = last.get("connected") is not None
            self._hopper_fill_raw = last.get("fill")
            dispensed = last.get("dispensed")
            self._last_hopper_dispensed = dt_util.parse_datetime(dispensed) if dispensed else None
            # …including the deduplication window, which is otherwise the one piece
            # of that dispense the reload drops. This coordinator is built seconds
            # after the dispense that proved the hopper, so a QoS-1 redelivery of
            # that same dispense would land on a fresh window, count as a second
            # sample, and corroborate an empty floor from a single physical
            # dispense — which is the thing corroboration exists to prevent.
            # Wall clock, because loop.time() means nothing across a reload.
            if self._last_hopper_dispensed is not None:
                age = (dt_util.utcnow() - self._last_hopper_dispensed).total_seconds()
                if 0 <= age < _DISPENSE_DEDUPE:
                    self._last_hopper_sample_at = hass.loop.time() - age



    @callback
    def _learn_hopper(self, raw: int) -> None:
        """Fold one FRESH dispense gauge reading into the hopper scale.

        Deliberately driven by the dispense event rather than by state
        documents: the last reading is retained between dispenses, so sampling
        it on every heartbeat would let a single bad value corroborate itself
        within seconds and become an anchor.
        """
        # The activity subscription is QoS 1, so one dispense can be delivered
        # more than once, and counting a redelivery as a separate dispense would
        # let a single low reading confirm an empty floor on its own. Redelivery
        # is a TIME property: separate dispenses are cycles apart, redeliveries
        # arrive within seconds. Deduplicating by value instead would discard the
        # repeated floor readings that are the entire evidence for "empty".
        now = self.hass.loop.time()
        if now - self._last_hopper_sample_at < _DISPENSE_DEDUPE:
            return
        self._last_hopper_sample_at = now
        if self._learned_hopper.observe(
            raw,
            bounds=HOPPER_PLAUSIBLE,
            corroboration=HOPPER_CORROBORATION,
            count_hits=True,
        ):
            self._persist_learned()

    @callback
    def _persist_learned(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                CONF_LEARNED_LITTER: self._learned_litter.as_dict(),
                CONF_LEARNED_HOPPER: self._learned_hopper.as_dict(),
            },
        )

    @callback
    def _learn(self, robot: LitterRobot4State) -> None:
        """Fold this report into the learned scales, persisting real movement.

        Guarded three ways: only a settled robot is sampled, values outside the
        physically plausible band are discarded, and a new extreme has to be
        corroborated by a second reading before it becomes an anchor. See
        calibration.py.
        """
        # Same redelivery hazard as the hopper: a QoS 1 duplicate arriving
        # seconds later would corroborate the candidate it just created, which
        # is one reading masquerading as two.
        now = self.hass.loop.time()
        if now - self._last_litter_sample_at < _STATE_DEDUPE:
            return
        self._last_litter_sample_at = now

        moved = False
        if litter_is_sampleable(robot):
            assert robot.litter_level_mm is not None
            moved |= self._learned_litter.observe(
                robot.litter_level_mm,
                bounds=LITTER_PLAUSIBLE_MM,
                corroboration=LITTER_CORROBORATION_MM,
                max_span=LITTER_MAX_SPAN_MM,
            )
        if moved:
            # Only when something actually changed. A new extreme is rare, so
            # this is not the per-state-document write it might look like.
            self._persist_learned()

    @callback
    def _record_hopper_sighting(self) -> None:
        """Persist that this robot has a hopper, with the readings that proved it.

        Deliberately only writes state here. Enabling the entities happens in
        async_setup_entry, after the platforms have registered them, so this can
        never race platform setup; the reload below is what gets us there.
        """
        self._hopper_seen = True
        dispensed = self._last_hopper_dispensed
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                CONF_HOPPER_SEEN: True,
                CONF_HOPPER_LAST: {
                    "connected": self._hopper_connected,
                    "fill": self._hopper_fill_raw,
                    "dispensed": dispensed.isoformat() if dispensed else None,
                },
            },
        )
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    @property
    def litter_full_mm(self) -> int | None:
        """The calibrated reading when the globe is filled to the line."""
        value = self.config_entry.options.get(CONF_LITTER_FULL_MM)
        return int(value) if value is not None else None

    @property
    def litter_empty_mm(self) -> int | None:
        """The calibrated reading with the globe empty, if it was ever taken."""
        value = self.config_entry.options.get(CONF_LITTER_EMPTY_MM)
        return int(value) if value is not None else None

    async def async_calibrate_litter(self, *, empty: bool) -> None:
        """Store the current distance as the full or empty reference.

        Uses litter_level_mm rather than the percentage, because the percentage
        is the thing being calibrated. Refuses while the reading is suppressed
        (mid-cycle, or the filter wizard) — the ToF is looking at the globe, not
        the litter, and capturing that would bake in a garbage reference.
        """
        # The user has just filled or emptied the globe, so the cached snapshot
        # is exactly the wrong thing to measure. async_refresh() would not do:
        # with a heartbeat already in flight it queues and returns immediately,
        # leaving self.data on the pre-fill reading. Run the request-and-wait
        # transaction directly so the value stored is one the robot sent after
        # the button was pressed.
        try:
            data = await self._async_update_data()
        except UpdateFailed as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="litter_reading_unavailable"
            ) from err
        self.async_set_updated_data(data)
        robot = data.robot
        if robot.litter_level_mm is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="litter_reading_unavailable"
            )
        key = CONF_LITTER_EMPTY_MM if empty else CONF_LITTER_FULL_MM
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, key: robot.litter_level_mm},
        )
        # Republish: the calibration is copied into the data payload, so
        # listeners would otherwise re-read the old values and the press would
        # appear to do nothing until the next heartbeat.
        self.async_set_updated_data(self._build_data(robot))

    def _build_data(self, robot: LitterRobot4State) -> WhiskerlessData:
        """Combine the state snapshot with the activity-derived facts."""
        # The learned minimum is the fullest reading SEEN, a decent estimate of
        # a full fill because that is what people fill to, so it stands in for
        # the manual reference and anchors 90%. The learned maximum is NOT
        # evidence the globe was ever emptied, so it is never used as the zero
        # end: that would report "empty" at whatever level this robot happens to
        # sit lowest, which for most robots is an ordinary day.
        effective_full: int | None
        effective_empty: int | None
        if self.litter_full_mm is not None:
            effective_full = self.litter_full_mm
            effective_empty = self.litter_empty_mm
        else:
            effective_full = self._learned_litter.low
            effective_empty = None
        return WhiskerlessData(
            robot=robot,
            cat_weight_lb=self._cat_weight_lb,
            last_cat_visit=self._last_cat_visit,
            last_visit_duration_s=self._last_visit_duration_s,
            hopper_connected=self._hopper_connected,
            hopper_link_reported=self._hopper_link_reported,
            litter_full_mm=effective_full,
            litter_empty_mm=effective_empty,
            litter_reference_mm=self.litter_full_mm,
            hopper_fill_percent=(
                None
                if self._hopper_fill_raw is None
                else hopper_percent(self._hopper_fill_raw, self._learned_hopper)
            ),
            last_hopper_dispensed=self._last_hopper_dispensed,
            hopper_fill_raw=self._hopper_fill_raw,
            drawer_last_moved=self._drawer_last_moved,
        )

    @callback
    def _handle_activity_events(self, message: ActivityMessage) -> bool:
        """Fold an activity message's semantic events into the derived facts."""
        changed = False
        hopper_reported = False
        # A press we are waiting on, echoed back: the robot confirming it acted.
        if self._awaited_press is not None and any(
            r.register == lr4.Register.PANEL_BUTTON and r.value == self._awaited_press
            for r in message.readings
        ):
            self._press_echo.set()
        for event in events_from_readings(message.readings):
            if isinstance(event, HopperDispensed) or (
                isinstance(event, HopperLinkChanged) and event.connected
            ):
                hopper_reported = True
            if isinstance(event, CatWeightMeasured):
                self._cat_weight_lb = event.weight_lb
                self._last_cat_visit = dt_util.utcnow()
                changed = True
            elif isinstance(event, HopperDispensed):
                self._last_hopper_dispensed = dt_util.utcnow()
                # Dispensing is proof of a working link, same as a 0x57 report.
                self._hopper_link_reported = True
                self._hopper_connected = True  # it just dispensed
                if event.phase == lr4.HOPPER_DISPENSE_FILL_PHASE:
                    self._hopper_fill_raw = event.value
                    self._learn_hopper(event.value)
                changed = True
            elif isinstance(event, HopperLinkChanged):
                first_report = not self._hopper_link_reported
                self._hopper_link_reported = True
                # An unnamed code is not evidence of a disconnect, so it must not
                # overwrite a link state the robot has already told us. `-30` was
                # captured repeating once a minute while the hopper was attached,
                # dispensing, and reporting a healthy gauge, then cleared itself —
                # reporting that as unknown described a working hopper as a mystery.
                # With nothing known yet, unknown is still the honest answer, so a
                # first report is published whatever it says.
                if event.connected is None and not first_report:
                    continue
                if first_report or event.connected != self._hopper_connected:
                    self._hopper_connected = event.connected
                    changed = True
            elif isinstance(event, CatVisitEnded):
                # The duration closes a visit even when it was too short for a
                # weight event, so it also stamps last_cat_visit.
                self._last_visit_duration_s = event.duration_s
                self._last_cat_visit = dt_util.utcnow()
                changed = True
            elif isinstance(event, DrawerBayMoved):
                self._drawer_last_moved = dt_util.utcnow()
                changed = True
        if hopper_reported and not self._hopper_seen:
            self._record_hopper_sighting()
        return changed


    @override
    async def _async_setup(self) -> None:
        """Wait for MQTT, subscribe to this robot's topics, prompt a first state."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="mqtt_unavailable"
            )
        # Register via async_on_unload so the subscription is torn down even when
        # the first refresh fails (SETUP_RETRY) — otherwise it leaks per retry.
        self.config_entry.async_on_unload(
            await mqtt.async_subscribe(
                self.hass, subscribe_topic(self.serial), self._handle_message, qos=1
            )
        )
        await self._publish(commands.request_state())

    @callback
    def _handle_message(self, message: ReceiveMessage) -> None:
        """Decode an inbound MQTT message and push it to entities (never blocks)."""
        try:
            parsed = parse_message(message.topic, message.payload)
            if isinstance(parsed, StateMessage):
                self._robot = parsed.state
                self._learn(parsed.state)
                self._state_event.set()
                self.async_set_updated_data(self._build_data(parsed.state))
            elif isinstance(parsed, ActivityMessage):
                if self._handle_activity_events(parsed) and self._robot is not None:
                    self.async_set_updated_data(self._build_data(self._robot))
                self._schedule_activity_refresh()
        except Exception:  # noqa: BLE001 — a bad message must never break the subscription
            LOGGER.exception("Error handling MQTT message for %s", self.serial)

    @callback
    def _schedule_activity_refresh(self) -> None:
        """Prompt a throttled full-state refresh after a telemetry event."""
        if self._io_lock.locked():
            # A write is mid-transaction. Every accepted register write echoes as
            # an activity message, so refreshing here would fire a requestState
            # into the gap between two paced writes — reintroducing the
            # back-to-back traffic the pacing exists to avoid. That transaction
            # requests its own state anyway.
            return
        now = self.hass.loop.time()
        if now - self._last_activity_refresh < _ACTIVITY_THROTTLE:
            return
        self._last_activity_refresh = now
        task = self.hass.async_create_task(self._safe_request_state())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safe_request_state(self) -> None:
        with contextlib.suppress(WhiskerlessError, HomeAssistantError):
            # Under the lock, not merely skipped when it looked free at schedule
            # time: this runs as a task, so a write can take the lock in between
            # and the publish would land in one of its pacing gaps.
            async with self._io_lock:
                await self._publish(commands.request_state())

    @override
    async def _async_update_data(self) -> WhiskerlessData:
        """Heartbeat / first refresh: prompt a fresh state and return it."""
        async with self._io_lock:
            self._state_event.clear()
            await self._publish(commands.request_state())
            try:
                async with asyncio.timeout(_STATE_TIMEOUT):
                    await self._state_event.wait()
            except TimeoutError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN, translation_key="no_response"
                ) from err
            assert self._robot is not None
            return self._build_data(self._robot)

    @override
    async def async_shutdown(self) -> None:
        """Cancel in-flight refresh tasks (the subscription is dropped on unload)."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await super().async_shutdown()

    # --- publishing (every send is guarded) ----------------------------------
    async def _publish(self, command: Command, *, allow_dangerous: bool = False) -> None:
        # Every send is classified, including the ones this integration builds
        # itself: the guard is the one chokepoint, not a check on user input.
        assert_sendable(command.code, allow_dangerous=allow_dangerous)
        await mqtt.async_publish(
            self.hass,
            command_topic(self.serial),
            build_command_payload(self.serial, command.code),
            qos=0 if command.at_most_once else 1,
        )

    async def _write_and_verify(
        self,
        command: Command | Sequence[Command],
        verify: Callable[[LitterRobot4State], bool],
        *,
        retries: int = 3,
    ) -> None:
        batch = [command] if isinstance(command, Command) else list(command)
        label = batch[0].label if len(batch) == 1 else f"{batch[0].label} ×{len(batch)}"
        async with self._io_lock:
            for _ in range(retries):
                self._state_event.clear()
                for index, item in enumerate((*batch, commands.request_state())):
                    if index:
                        await asyncio.sleep(_WRITE_GAP)
                    await self._publish(item)
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(_VERIFY_TIMEOUT):
                        while True:
                            await self._state_event.wait()
                            self._state_event.clear()
                            if self._robot is not None and verify(self._robot):
                                self.async_set_updated_data(self._build_data(self._robot))
                                return
        raise WhiskerlessError(f"{label} did not commit")

    # --- public commands the entities call -----------------------------------
    async def async_set_night_light_mode(self, mode: int) -> None:
        expected = lr4.NIGHT_LIGHT_MODE.get(mode)
        await self._write_and_verify(
            commands.set_night_light_mode(mode), lambda s: s.night_light_mode == expected
        )

    async def async_set_night_light_brightness(self, percent: int) -> None:
        await self._write_and_verify(
            commands.set_night_light_brightness(percent),
            lambda s: s.night_light_brightness == percent,
        )

    async def async_set_panel_brightness(self, high: int, low: int) -> None:
        command = commands.set_panel_brightness(high, low)
        # Against the value actually encoded: the builder clamps, and comparing with
        # the caller's numbers would call a clamped-but-applied write a failure.
        sent_high, sent_low = divmod(command.value or 0, 0x100)
        await self._write_and_verify(
            command,
            lambda s: s.display_intensity_high == sent_high
            and s.display_intensity_low == sent_low,
        )

    async def async_set_clean_cycle_wait(self, minutes: int) -> None:
        await self._write_and_verify(
            commands.set_clean_cycle_wait_minutes(minutes),
            lambda s: s.clean_cycle_wait_minutes == minutes,
        )

    async def async_set_keypad_lockout(self, enabled: bool) -> None:
        await self._write_and_verify(
            commands.set_keypad_lockout(enabled), lambda s: s.keypad_lockout == enabled
        )

    async def _press_and_confirm(
        self,
        command: Command,
        *,
        confirms: Callable[[LitterRobot4State], bool] | None = None,
        allow_dangerous: bool = False,
    ) -> None:
        """Send a panel-button press exactly once and confirm the robot acted.

        Deliberately NOT retried. Publishing is at-most-once, and a missing echo
        does not mean the press was missed — the press can land and its echo be
        lost, so resending could press twice. A doubled cycle is worse than a
        press the user simply repeats, and there is no request id to make the
        action idempotent.

        Confirmation is the robot echoing the button register. If that never
        arrives and the action has an observable effect, ``confirms`` checks a
        FRESHLY fetched state, so a lost echo alone does not report failure. It
        must be fresh: the cached snapshot may already satisfy the predicate for
        unrelated reasons, which would turn "no evidence" into a false success.
        """
        async with self._io_lock:
            self._press_echo.clear()
            self._awaited_press = command.value
            try:
                await self._publish(command, allow_dangerous=allow_dangerous)
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(_PRESS_TIMEOUT):
                        await self._press_echo.wait()
                    # The press is confirmed from here. The refresh is a courtesy,
                    # so its failure must not report a landed press as failed —
                    # that would invite the user to press an edge-triggered
                    # action a second time.
                    with contextlib.suppress(WhiskerlessError, HomeAssistantError):
                        await asyncio.sleep(_WRITE_GAP)
                        await self._publish(commands.request_state())
                    return
            finally:
                self._awaited_press = None

            # No echo. Ask the robot directly rather than assume either way.
            if confirms is not None:
                self._state_event.clear()
                await self._publish(commands.request_state())
                fresh = False
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(_VERIFY_TIMEOUT):
                        await self._state_event.wait()
                        fresh = True
                if fresh and self._robot is not None and confirms(self._robot):
                    return
        raise WhiskerlessError(
            f"{command.label} was not acknowledged — check the robot before repeating it"
        )

    async def async_clean_cycle(self) -> None:
        """Run a clean cycle. The robot reports its own progress from there."""
        # Specifically clean_cycle, not is_cleaning: the boot cycle also counts as
        # cleaning, so a press sent during one would be "confirmed" by a cycle it
        # had nothing to do with.
        await self._press_and_confirm(
            commands.clean_cycle(), confirms=lambda s: s.robot_status == "clean_cycle"
        )

    async def async_empty_cycle(self) -> None:
        """Run an empty cycle: the globe dumps every gram of litter and parks.

        Confirmed against the empty odometer rather than ``robot_status``: no
        capture has ever shown which integer a local robot reports during an
        empty cycle, so the status this would have to match is unknown, while
        ``odometerEmptyCycles`` is in every state document and moves once per run.
        """
        before = self.data.robot.odometer_empty_cycles
        await self._press_and_confirm(
            commands.empty_cycle(),
            confirms=lambda s: (
                before is not None
                and s.odometer_empty_cycles is not None
                and s.odometer_empty_cycles != before
            ),
        )

    async def async_power_toggle(self) -> None:
        """Press Power, which toggles the robot on or off.

        The only command here that opts past the safety guard, and the only one
        that can end with the robot unreachable: powered off, it leaves the
        network, and nothing on this connection can bring it back. The entity is
        disabled by default for the same reason.

        No state fallback. If the press turned the robot OFF then silence is the
        expected outcome, so asking for fresh state and getting nothing would
        prove nothing either way.
        """
        await self._press_and_confirm(commands.power_toggle(), allow_dangerous=True)

    async def async_panel_reset(self) -> None:
        """Press Reset: acknowledge a full alarm, or release a stalled cycle.

        No state fallback: from idle a reset leaves no lasting mark in the state
        document, so there is nothing to check that would not also be true had
        the press never happened.
        """
        await self._press_and_confirm(commands.panel_reset())

    async def async_set_panel_sleep_mode(self, enabled: bool) -> None:
        try:
            # 0x1A is derived from the weekday schedule, not a setting of its own, so
            # this is attempted once rather than retried: repeating a write the
            # firmware structurally ignores just makes the user wait three timeouts
            # for the same answer.
            await self._write_and_verify(
                commands.set_panel_sleep_mode(enabled),
                lambda s: s.panel_sleep_mode == enabled,
                retries=1,
            )
        except WhiskerlessError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_sleep_not_writable"
            ) from err

    async def async_set_weekday_sleep_enabled(self, enabled: bool) -> None:
        await self._write_and_verify(
            commands.set_weekday_sleep_enabled(enabled),
            lambda s: weekday_sleep_days_match(s, enabled),
        )

    async def async_set_panel_sleep_time(self, minutes: int) -> None:
        # Every day is checked rather than 0x1B: that mirrors today only, so it would
        # pass while another day's write was dropped, and pass instantly whenever
        # today already held the requested time.
        await self._write_and_verify(
            commands.set_panel_sleep_times(minutes),
            lambda s: every_weekday_is(s.weekday_sleep_times, minutes),
        )

    async def async_set_panel_wake_time(self, minutes: int) -> None:
        await self._write_and_verify(
            commands.set_panel_wake_times(minutes),
            lambda s: every_weekday_is(s.weekday_wake_times, minutes),
        )
