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
from typing import override

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_4 import LitterRobot4State, commands
from whiskerless.devices.litter_robot_4 import const as lr4
from whiskerless.devices.litter_robot_4.commands import Command
from whiskerless.devices.litter_robot_4.const import command_topic, subscribe_topic
from whiskerless.devices.litter_robot_4.protocol import (
    ActivityMessage,
    StateMessage,
    build_command_payload,
    parse_message,
)
from whiskerless.safety import assert_sendable

from .const import CONF_SERIAL, DEFAULT_NAME, DOMAIN, HEARTBEAT_INTERVAL, LOGGER

type WhiskerlessConfigEntry = ConfigEntry[WhiskerlessCoordinator]

_STATE_TIMEOUT = 10.0
_VERIFY_TIMEOUT = 8.0
_ACTIVITY_THROTTLE = 2.0


@dataclass
class WhiskerlessData:
    """The coordinator's data payload."""

    robot: LitterRobot4State


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
                self.async_set_updated_data(WhiskerlessData(robot=parsed.state))
            elif isinstance(parsed, ActivityMessage):
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
            return WhiskerlessData(robot=self._robot)

    @override
    async def async_shutdown(self) -> None:
        """Cancel in-flight refresh tasks (the subscription is dropped on unload)."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await super().async_shutdown()

    # --- publishing (every send is guarded) ----------------------------------
    async def _publish(self, command: Command, *, allow_motor: bool = False) -> None:
        assert_sendable(command.code, allow_motor=allow_motor)
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
                                self.async_set_updated_data(WhiskerlessData(robot=self._robot))
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

    async def async_start_clean_cycle(self) -> None:
        await self._publish(commands.clean_cycle(), allow_motor=True)
