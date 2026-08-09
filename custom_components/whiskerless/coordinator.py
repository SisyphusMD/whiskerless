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
from collections.abc import Callable
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
from whiskerless.devices.litter_robot_4 import LitterRobot4State, commands
from whiskerless.devices.litter_robot_4 import const as lr4
from whiskerless.devices.litter_robot_4.commands import Command
from whiskerless.devices.litter_robot_4.const import command_topic, subscribe_topic
from whiskerless.devices.litter_robot_4.events import (
    CatVisitEnded,
    CatWeightMeasured,
    DrawerBayChanged,
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
_ACTIVITY_THROTTLE = 2.0

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
    litter_full_mm: int | None = None
    litter_empty_mm: int | None = None
    last_hopper_dispensed: datetime | None = None
    hopper_fill_raw: int | None = None
    drawer_removed: bool | None = None


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
        self._last_hopper_dispensed: datetime | None = None
        self._hopper_fill_raw: int | None = None
        self._drawer_removed: bool | None = None
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
        return WhiskerlessData(
            robot=robot,
            cat_weight_lb=self._cat_weight_lb,
            last_cat_visit=self._last_cat_visit,
            last_visit_duration_s=self._last_visit_duration_s,
            hopper_connected=self._hopper_connected,
            hopper_link_reported=self._hopper_link_reported,
            litter_full_mm=self.litter_full_mm,
            litter_empty_mm=self.litter_empty_mm,
            last_hopper_dispensed=self._last_hopper_dispensed,
            hopper_fill_raw=self._hopper_fill_raw,
            drawer_removed=self._drawer_removed,
        )

    @callback
    def _handle_activity_events(self, message: ActivityMessage) -> bool:
        """Fold an activity message's semantic events into the derived facts."""
        changed = False
        hopper_reported = False
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
                changed = True
            elif isinstance(event, HopperLinkChanged):
                # Always republish: the first reading may be an unnamed fault,
                # which is None and must surface as unknown rather than leaving
                # the entity on whatever it restored.
                first_report = not self._hopper_link_reported
                self._hopper_link_reported = True
                if first_report or event.connected != self._hopper_connected:
                    self._hopper_connected = event.connected
                    changed = True
            elif isinstance(event, CatVisitEnded):
                # The duration closes a visit even when it was too short for a
                # weight event, so it also stamps last_cat_visit.
                self._last_visit_duration_s = event.duration_s
                self._last_cat_visit = dt_util.utcnow()
                changed = True
            elif isinstance(event, DrawerBayChanged):
                if event.removed != self._drawer_removed:
                    self._drawer_removed = event.removed
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
        now = self.hass.loop.time()
        if now - self._last_activity_refresh < _ACTIVITY_THROTTLE:
            return
        self._last_activity_refresh = now
        task = self.hass.async_create_task(self._safe_request_state())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safe_request_state(self) -> None:
        with contextlib.suppress(WhiskerlessError, HomeAssistantError):
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
    async def _publish(self, command: Command) -> None:
        assert_sendable(command.code)
        await mqtt.async_publish(
            self.hass,
            command_topic(self.serial),
            build_command_payload(self.serial, command.code),
            qos=1,
        )

    async def _write_and_verify(
        self,
        command: Command,
        verify: Callable[[LitterRobot4State], bool],
        *,
        retries: int = 3,
    ) -> None:
        async with self._io_lock:
            for _ in range(retries):
                self._state_event.clear()
                await self._publish(command)
                await self._publish(commands.request_state())
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(_VERIFY_TIMEOUT):
                        while True:
                            await self._state_event.wait()
                            self._state_event.clear()
                            if self._robot is not None and verify(self._robot):
                                self.async_set_updated_data(self._build_data(self._robot))
                                return
        raise WhiskerlessError(f"{command.label} did not commit")

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
        await self._write_and_verify(
            commands.set_panel_brightness(high, low),
            lambda s: s.display_intensity_high == high and s.display_intensity_low == low,
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

    async def async_set_panel_sleep_mode(self, enabled: bool) -> None:
        await self._write_and_verify(
            commands.set_panel_sleep_mode(enabled), lambda s: s.panel_sleep_mode == enabled
        )

    async def async_set_weekday_sleep_enabled(self, enabled: bool) -> None:
        await self._write_and_verify(
            commands.set_weekday_sleep_enabled(enabled),
            lambda s: s.weekday_sleep_enabled == enabled,
        )

    async def async_set_panel_sleep_time(self, minutes: int) -> None:
        await self._write_and_verify(
            commands.set_panel_sleep_time(minutes), lambda s: s.panel_sleep_time == minutes
        )

    async def async_set_panel_wake_time(self, minutes: int) -> None:
        await self._write_and_verify(
            commands.set_panel_wake_time(minutes), lambda s: s.panel_wake_time == minutes
        )
