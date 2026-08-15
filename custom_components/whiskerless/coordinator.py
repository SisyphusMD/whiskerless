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
from typing import override

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_NAME, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_4 import (
    LitterRobot4State,
    commands,
    derive,
    every_weekday_is,
    weekday_sleep_days_match,
)
from whiskerless.devices.litter_robot_4 import const as lr4
from whiskerless.devices.litter_robot_4.commands import Command
from whiskerless.devices.litter_robot_4.const import command_topic, subscribe_topic
from whiskerless.devices.litter_robot_4.derive import (
    Capability,
    CapabilitySighted,
    DerivedState,
    Effect,
    Evidence,
    FirmwareChanged,
    HopperFillChanged,
    LearnedChanged,
)
from whiskerless.devices.litter_robot_4.protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)
from whiskerless.safety import assert_sendable

from .const import (
    CONF_CAT_VISIT_SEEN,
    CONF_DERIVED,
    CONF_DRAWER_SEEN,
    CONF_HOPPER_FILL_RAW,
    CONF_HOPPER_SEEN,
    CONF_LEARNED_HOPPER,
    CONF_LEARNED_LITTER,
    CONF_LITTER_EMPTY_MM,
    CONF_LITTER_FULL_MM,
    CONF_PET_WEIGHT_SEEN,
    CONF_SERIAL,
    CONF_VISIT_DURATION_SEEN,
    DEFAULT_NAME,
    DOMAIN,
    HEARTBEAT_INTERVAL,
    LOGGER,
)

#: Which config-entry option records each capability's first sighting. The
#: library decides what counts as proof; Home Assistant decides where it is kept.
SIGHTING_OPTIONS: dict[Capability, str] = {
    Capability.HOPPER: CONF_HOPPER_SEEN,
    Capability.VISIT_DURATION: CONF_VISIT_DURATION_SEEN,
    Capability.DRAWER: CONF_DRAWER_SEEN,
    Capability.PET_WEIGHT: CONF_PET_WEIGHT_SEEN,
    Capability.CAT_VISIT: CONF_CAT_VISIT_SEEN,
}

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
# How long to wait for the robot to echo a panel-button press. The echo is the
# robot's own acknowledgement that it acted, which QoS 1 cannot give — that only
# proves the broker accepted the message.
_PRESS_TIMEOUT = 5.0


@dataclass
class WhiskerlessData:
    """The coordinator's data payload.

    ``robot`` is the latest full-state snapshot; ``derived`` is everything the
    library assembled from the streams over time (per-visit cat weight, hopper
    dispenses, the learned scales). The calibration pair rides along because it
    lives on the config entry, which is Home Assistant's business, not the
    library's.
    """

    robot: LitterRobot4State
    derived: DerivedState
    # The pair actually used for the percentage: the user's measurements when
    # they exist, otherwise the learned extremes once they span enough to trust.
    litter_full_mm: int | None = None
    litter_empty_mm: int | None = None
    # What the user measured, for the diagnostic sensor. Deliberately not the
    # learned value: "at the line" is a claim only a person can make.
    litter_reference_mm: int | None = None


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
        self._derived = self._restore_derived()
        self._press_echo = asyncio.Event()
        self._awaited_press: int | None = None

    def _restore_derived(self) -> DerivedState:
        """Rebuild the derived state from what was stored for this robot.

        Two kinds of option feed it. The DURABLE ones — the learned scales, the
        last fill gauge, the sightings — are each written when they change and
        always win, because they are the newest copy of themselves. The
        bootstrap blob is a full snapshot written the moment a sighting was
        recorded, and exists only so the entities that sighting enables have a
        value the instant they appear: enabling one reloads the entry, which
        builds a fresh coordinator that would otherwise discard the very
        readings that proved the capability.
        """
        options = self.config_entry.options
        stored = dict(options.get(CONF_DERIVED) or {})
        for field, durable in (
            ("learned_litter", CONF_LEARNED_LITTER),
            ("learned_hopper", CONF_LEARNED_HOPPER),
            ("hopper_fill_raw", CONF_HOPPER_FILL_RAW),
        ):
            if options.get(durable) is not None:
                stored[field] = options[durable]
        # One tolerant path in, so a hand-edited or older option can only be
        # ignored, never break setup for the entry it belongs to.
        derived = DerivedState.from_dict(stored)
        derived.sightings = {
            capability: derived.sightings.get(capability, Evidence.LEGACY)
            for capability, seen_key in SIGHTING_OPTIONS.items()
            if options.get(seen_key)
        }
        derived.globe_fault_restored = self._restored_verdict("globe_motor_fault")
        derived.excess_weight_restored = self._restored_verdict("excess_weight")
        # A recorded sighting means this robot was watched delivering litter, and
        # there is no signal that would ever retract that. Deriving it here rather
        # than leaning on the entity's restore cache also discards any `off` left
        # behind by the old 0x57 handling, which could park the sensor on
        # "disconnected" for good after a refill.
        if derived.sighted(Capability.HOPPER):
            derived.hopper_connected = True
        return derived

    def _restored_verdict(self, key: str) -> bool | None:
        """What a latching binary sensor last reported, from the restore cache.

        Read here rather than in the entity so the rule for when a carried
        verdict expires can live in the library beside the rule that raised it.
        The entities stay RestoreEntity, which is what writes the cache; this is
        the read side, the same way the hopper gauge is seeded at setup.
        """
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, f"{self.serial}_{key}"
        )
        stored = restore_state.async_get(self.hass).last_states.get(entity_id) if entity_id else None
        if stored is None or stored.state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        return stored.state.state == STATE_ON

    @callback
    def _apply_effects(self, effects: Sequence[Effect]) -> None:
        """Store what the library says is worth keeping, in one entry write.

        Enabling the entities a sighting unlocks happens in async_setup_entry,
        after the platforms have registered them, so this only records state and
        schedules the reload that gets us there — once per message, however many
        sightings it proved, because each reload is a full unload/setup cycle.
        """
        options = dict(self.config_entry.options)
        sighted = False
        for effect in effects:
            if isinstance(effect, LearnedChanged):
                options[CONF_LEARNED_LITTER] = self._derived.learned_litter.as_dict()
                options[CONF_LEARNED_HOPPER] = self._derived.learned_hopper.as_dict()
            elif isinstance(effect, HopperFillChanged):
                options[CONF_HOPPER_FILL_RAW] = effect.value
            elif isinstance(effect, CapabilitySighted):
                # The evidence, not a bare flag: a later change to what counts
                # as proof can then retire this sighting or leave it alone on
                # its own merits.
                options[SIGHTING_OPTIONS[effect.capability]] = str(effect.evidence)
                sighted = True
            elif isinstance(effect, FirmwareChanged):
                # Device info is registered when entities are added, so an OTA
                # landing while the entry stays loaded would otherwise show the
                # old firmware until the next reload.
                self._refresh_device_firmware(effect.version)
        if sighted:
            options[CONF_DERIVED] = self._derived.as_dict()
        if options != dict(self.config_entry.options):
            self.hass.config_entries.async_update_entry(self.config_entry, options=options)
        if sighted:
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
        """Combine the state snapshot with everything derived so far."""
        full_mm, empty_mm = derive.litter_scale(
            self._derived, full_mm=self.litter_full_mm, empty_mm=self.litter_empty_mm
        )
        return WhiskerlessData(
            robot=robot,
            derived=self._derived,
            litter_full_mm=full_mm,
            litter_empty_mm=empty_mm,
            litter_reference_mm=self.litter_full_mm,
        )

    @callback
    def _watch_press_echo(self, message: ActivityMessage) -> None:
        """A press we are waiting on, echoed back: the robot confirming it acted."""
        if self._awaited_press is not None and any(
            r.register == lr4.Register.PANEL_BUTTON and r.value == self._awaited_press
            for r in message.readings
        ):
            self._press_echo.set()


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
        if self.config_entry.state is ConfigEntryState.UNLOAD_IN_PROGRESS:
            # The MQTT unsubscribe runs via async_on_unload AFTER the platforms
            # unload, so a message landing in that gap would fold state into a
            # dying coordinator — or schedule a reload of an entry being removed.
            return
        try:
            parsed = parse_message(message.topic, message.payload)
            if parsed is None:
                return
            if isinstance(parsed, ActivityMessage):
                # Before the reducer, which is deliberately blind to our own
                # traffic: the echo is transport, not a fact about the robot.
                self._watch_press_echo(parsed)
            update = derive.apply_message(self._derived, parsed, dt_util.utcnow())
            self._derived = update.state
            self._apply_effects(update.effects)
            if isinstance(parsed, StateMessage):
                self._robot = parsed.state
                self._state_event.set()
                self.async_set_updated_data(self._build_data(parsed.state))
            else:
                if update.changed and self._robot is not None:
                    self.async_set_updated_data(self._build_data(self._robot))
                self._schedule_activity_refresh()
        except Exception:  # noqa: BLE001 — a bad message must never break the subscription
            LOGGER.exception("Error handling MQTT message for %s", self.serial)

    @callback
    def _refresh_device_firmware(self, firmware: str) -> None:
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.serial)})
        if device is not None:
            registry.async_update_device(device.id, sw_version=firmware)

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
        command = commands.set_night_light_mode(mode)
        # Against the value actually encoded: the builder clamps, and comparing
        # with the caller's number would call a clamped-but-applied write a failure.
        expected = lr4.NIGHT_LIGHT_MODE.get(command.value if command.value is not None else mode)
        await self._write_and_verify(command, lambda s: s.night_light_mode == expected)

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
            # No baseline means the odometer cannot confirm anything — fall back
            # to echo-only rather than fetching a state doomed to read as failure.
            confirms=(
                None
                if before is None
                else lambda s: (
                    s.odometer_empty_cycles is not None and s.odometer_empty_cycles != before
                )
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
