"""Push state container for one Litter-Robot EVO.

The EVO has no state document, but most of its registers can be read. The
coordinator subscribes to the robot's topics, folds every message into a
:class:`LitterRobotEvoState`, and reads every readable register in one message
shortly after the entry is set up and whenever the robot reconnects or powers
up, so status, hardware state and settings show real values straight away. The
display code and the weight sensor cannot be read; they fill in from telemetry.

The setup read waits a few seconds: Home Assistant's MQTT client sends new
subscriptions to the broker after a cooldown, and a reply published before the
subscription reaches the broker is lost. A read that gets no reply is repeated a
bounded number of times, and until a reply arrives, any message from the robot
schedules another read.

Each read sequence also keeps the robot's clock, which its sleep schedule runs
on, set to Home Assistant's local time: the first reply of the sequence shows the
robot is listening, and one clock write follows it.

Writes are verified by their echo: the robot answers every accepted write on
its activity topic with the address and the value it applied. A setting must
echo the value written; an action is acknowledged by any echo at its address,
because the robot reports the resulting status rather than the value written.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, override

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from whiskerless import WhiskerlessError
from whiskerless.devices.litter_robot_evo import (
    ActivityMessage,
    EventMessage,
    LitterRobotEvoState,
    PawprintMessage,
    apply_message,
    build_command_payload,
    commands,
    const,
    parse_message,
)
from whiskerless.devices.litter_robot_evo.commands import Command
from whiskerless.safety import assert_evo_sendable

from ..const import CONF_SERIAL, DEFAULT_NAME_EVO, DOMAIN, LOGGER, SIGNAL_EVO_EVENT

#: How long a write waits for the robot's echo before it is retried.
_ECHO_TIMEOUT = 5.0
#: Attempts per write, the first included.
_ATTEMPTS = 2
#: Seconds after a reconnect or power-up before the registers are read, so one
#: read follows the burst of display codes the robot sends while it settles.
_READ_DELAY = 3.0
#: Seconds after setup before the first read, so the subscription is live at the
#: broker before the robot answers.
_SETUP_READ_DELAY = 5.0
#: Seconds a read waits for its ``query`` reply before it is sent again.
_READ_REPLY_TIMEOUT = 10.0
#: Reads per attempt sequence, the first included.
_READ_ATTEMPTS = 3
#: Display codes the robot shows while it connects or powers up.
_RECONNECT_DISPLAY_CODES = frozenset({0x66, 0x67})
_DISPLAY_ADDRESS = (const.Bank.ROBOT, const.RobotRegister.DISPLAY_CODE)

type WhiskerlessEvoConfigEntry = ConfigEntry[WhiskerlessEvoCoordinator]


class WhiskerlessEvoCoordinator(DataUpdateCoordinator[LitterRobotEvoState]):
    """Subscribes to one EVO via HA's MQTT and pushes its state to entities."""

    config_entry: WhiskerlessEvoConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry[Any]) -> None:
        """Initialize the coordinator. No update interval: the robot pushes."""
        super().__init__(hass, LOGGER, config_entry=config_entry, name=DOMAIN)
        self.serial: str = config_entry.data[CONF_SERIAL]
        self.device_name: str = config_entry.data.get(CONF_NAME) or DEFAULT_NAME_EVO
        self._state = LitterRobotEvoState()
        self._io_lock = asyncio.Lock()
        self._awaited: tuple[int, int] | None = None
        self._echo: asyncio.Future[int] | None = None
        self._read_unsub: CALLBACK_TYPE | None = None
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._read_attempts = 0
        #: Whether a read has been answered since setup.
        self._seeded = False
        #: Whether the current read sequence still owes the robot a clock write.
        self._clock_pending = False

    @override
    async def _async_setup(self) -> None:
        """Wait for MQTT, subscribe to this robot's topics, and schedule a read."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN, translation_key="mqtt_unavailable"
            )
        self.config_entry.async_on_unload(
            await mqtt.async_subscribe(
                self.hass, const.subscribe_topic(self.serial), self._handle_message, qos=1
            )
        )
        self.config_entry.async_on_unload(self._cancel_reads)
        self._schedule_read(_SETUP_READ_DELAY)

    @override
    async def _async_update_data(self) -> LitterRobotEvoState:
        """Return the state folded from reads, telemetry and echoes."""
        return self._state

    async def async_read_state(self) -> None:
        """Read every readable register in one message.

        The robot answers with one ``query`` reply, which folds into state through
        the subscription like any other message. A read with no reply within
        ``_READ_REPLY_TIMEOUT`` is sent again, up to ``_READ_ATTEMPTS`` reads in
        all. A failed publish is logged, not raised: telemetry still fills the
        entities in.
        """
        self._read_attempts += 1
        self._arm_read_retry()
        try:
            await self._publish(commands.read_all(), allow_dangerous=False)
        except Exception:  # noqa: BLE001 — a missed read must not fail setup
            LOGGER.warning("Could not read the state of %s", self.serial, exc_info=True)

    async def async_set_clock(self) -> None:
        """Set the robot's clock to Home Assistant's local time, in one message.

        A failed publish is logged, not raised: the next read sequence tries again.
        """
        try:
            await self._publish(commands.set_clock(dt_util.now()), allow_dangerous=False)
        except Exception:  # noqa: BLE001 — a missed clock write must not break anything
            LOGGER.warning("Could not set the clock of %s", self.serial, exc_info=True)

    def _schedule_read(self, delay: float = _READ_DELAY) -> None:
        """Start a new read sequence after ``delay``, replacing any pending one."""
        self._cancel_reads()
        self._read_attempts = 0
        self._clock_pending = True
        self._read_unsub = async_call_later(self.hass, delay, self._scheduled_read)

    @callback
    def _scheduled_read(self, _now: object) -> None:
        self._read_unsub = None
        self._start_read()

    @callback
    def _start_read(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self.async_read_state(), f"{DOMAIN}_evo_read_{self.serial}"
        )

    def _arm_read_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
        self._retry_unsub = async_call_later(self.hass, _READ_REPLY_TIMEOUT, self._read_timed_out)

    @callback
    def _read_timed_out(self, _now: object) -> None:
        self._retry_unsub = None
        if self._read_attempts < _READ_ATTEMPTS:
            self._start_read()
            return
        LOGGER.info(
            "%s did not answer %d reads; its state fills in from telemetry",
            self.serial,
            self._read_attempts,
        )

    @callback
    def _cancel_reads(self) -> None:
        if self._read_unsub is not None:
            self._read_unsub()
            self._read_unsub = None
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    @callback
    def _handle_message(self, message: ReceiveMessage) -> None:
        """Fold an inbound message into state and resolve a pending write."""
        if self.config_entry.state is ConfigEntryState.UNLOAD_IN_PROGRESS:
            return
        try:
            parsed = parse_message(message.topic, message.payload)
            if parsed is None:
                return
            if isinstance(parsed, ActivityMessage) and parsed.query:
                self._seeded = True
                self._read_attempts = 0
                if self._retry_unsub is not None:
                    self._retry_unsub()
                    self._retry_unsub = None
                if self._clock_pending:
                    self._clock_pending = False
                    self.config_entry.async_create_background_task(
                        self.hass, self.async_set_clock(), f"{DOMAIN}_evo_clock_{self.serial}"
                    )
            elif isinstance(parsed, ActivityMessage):
                self._resolve_echo(parsed)
                if any(
                    reading.address == _DISPLAY_ADDRESS and reading.value in _RECONNECT_DISPLAY_CODES
                    for reading in parsed.readings
                ):
                    self._schedule_read()
            if (
                not self._seeded
                and self._read_unsub is None
                and self._retry_unsub is None
            ):
                # The robot is talking but no read has been answered: read now.
                self._schedule_read()
            state = apply_message(self._state, parsed)
            if state != self._state:
                self._state = state
                self.async_set_updated_data(state)
            if isinstance(parsed, EventMessage) or (
                isinstance(parsed, PawprintMessage) and parsed.pet_id_match is not None
            ):
                async_dispatcher_send(self.hass, SIGNAL_EVO_EVENT.format(self.serial), parsed)
        except Exception:  # noqa: BLE001 — a bad message must never break the subscription
            LOGGER.exception("Error handling MQTT message for %s", self.serial)

    def _resolve_echo(self, message: ActivityMessage) -> None:
        if self._echo is None or self._echo.done():
            return
        for reading in message.readings:
            if reading.address == self._awaited:
                self._echo.set_result(reading.value)
                return

    # --- publishing (every send is guarded) ----------------------------------
    async def _publish(self, batch: Sequence[Command], *, allow_dangerous: bool) -> None:
        for command in batch:
            assert_evo_sendable(command.code, allow_dangerous=allow_dangerous)
        await mqtt.async_publish(
            self.hass,
            const.command_topic(self.serial),
            build_command_payload(self.serial, *(command.code for command in batch)),
            qos=0 if any(command.at_most_once for command in batch) else 1,
        )

    async def _write(
        self, command: Command | Sequence[Command], *, allow_dangerous: bool = False
    ) -> None:
        """Publish ``command`` (one message) and wait for the last element's echo."""
        batch = [command] if isinstance(command, Command) else list(command)
        last = batch[-1]
        async with self._io_lock:
            for _ in range(_ATTEMPTS):
                self._awaited = last.address
                self._echo = self.hass.loop.create_future()
                try:
                    await self._publish(batch, allow_dangerous=allow_dangerous)
                    async with asyncio.timeout(_ECHO_TIMEOUT):
                        applied = await self._echo
                except TimeoutError:
                    continue
                finally:
                    self._awaited = None
                    self._echo = None
                if last.bank == const.Bank.SETTINGS and applied != last.value:
                    raise WhiskerlessError(
                        f"{last.label}: the robot applied 0x{applied:04X} instead"
                    )
                return
        raise WhiskerlessError(f"{last.label} was not acknowledged by the robot")

    # --- public commands the entities call -----------------------------------
    async def async_set_panel_brightness(self, screen: int, led: int) -> None:
        await self._write(commands.set_panel_brightness(screen, led))

    async def async_set_cycle_delay(self, minutes: int) -> None:
        await self._write(commands.set_cycle_delay(minutes))

    async def async_set_keypad_lockout(self, enabled: bool) -> None:
        await self._write(commands.set_keypad_lockout(enabled))

    async def async_set_sleep_enabled(self, enabled: bool) -> None:
        await self._write(commands.set_sleep_days(const.WEEKDAYS if enabled else ()))

    async def async_set_sleep_time(self, minutes: int) -> None:
        await self._write([commands.set_sleep_time(day, minutes) for day in const.WEEKDAYS])

    async def async_set_wake_time(self, minutes: int) -> None:
        await self._write([commands.set_wake_time(day, minutes) for day in const.WEEKDAYS])

    async def async_clean_cycle(self) -> None:
        await self._write(commands.clean_cycle())

    async def async_empty_cycle(self) -> None:
        await self._write(commands.empty_cycle())

    async def async_change_filter(self) -> None:
        await self._write(commands.change_filter())

    async def async_reset_drawer_level(self) -> None:
        await self._write(commands.reset_drawer_level())

    async def async_power_on(self) -> None:
        await self._write(commands.power_on())
        self._schedule_read()

    async def async_power_off(self) -> None:
        """Power the robot off. It stops cleaning until powered back on, so the
        command is classified dangerous and its entity is disabled by default."""
        await self._write(commands.power_off(), allow_dangerous=True)
