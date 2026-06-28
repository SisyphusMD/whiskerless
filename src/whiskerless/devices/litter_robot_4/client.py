"""Push-first Litter-Robot 4 client for long-lived consumers (the HA integration).

Owns a supervised MQTT connection: it subscribes once, keeps the latest decoded
:class:`LitterRobot4State`, and invokes a callback on every update so consumers
get *push* updates rather than polling. The connection self-heals on drop with
backoff and quiet logging (one warning on loss, one info on recovery).

Writes use the firmware's commit-latency-tolerant pattern: publish, prompt a
fresh state, and verify the change landed (retrying for the slow time-of-day
registers). Each long-lived client uses a distinct MQTT client-id so several
robots — and the robots' own connections — never evict each other from the broker.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import replace

import aiomqtt

from ...exceptions import WhiskerlessAuthError, WhiskerlessConnectionError, WhiskerlessError
from ...mqtt import MqttSettings
from . import commands
from .commands import Command
from .link import LitterRobot4Link
from .models import LitterRobot4State
from .protocol import ActivityMessage, StateMessage

log = logging.getLogger(__name__)

UpdateCallback = Callable[[LitterRobot4State], None]
StatePredicate = Callable[[LitterRobot4State], bool]

_RECONNECT_MAX_BACKOFF = 60.0
_ACTIVITY_REFRESH_THROTTLE = 2.0


class LitterRobot4Client:
    """A supervised, push-first connection to one robot."""

    def __init__(self, settings: MqttSettings, serial: str) -> None:
        self.serial = serial
        self.host = settings.host
        # Distinct from the robot's own client-id (== serial) and unique per robot,
        # so multiple HA entries + the robots themselves coexist on one broker.
        client_id = settings.client_id or f"whiskerless-ha-{serial}"
        self._settings = replace(settings, client_id=client_id)
        self._robot: LitterRobot4State | None = None
        self._callback: UpdateCallback | None = None
        self._link: LitterRobot4Link | None = None
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._ready = asyncio.Event()        # first successful connection
        self._failed = asyncio.Event()       # first connection attempt failed
        self._state_updated = asyncio.Event()
        self._first_error: BaseException | None = None
        self._available = False
        self._last_activity_refresh = 0.0
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # --- lifecycle -----------------------------------------------------------
    async def connect(self) -> None:
        """Open the supervised connection and wait until it is up.

        Raises :class:`WhiskerlessAuthError` / :class:`WhiskerlessConnectionError`
        if the first connection attempt fails.
        """
        self._closing = False
        self._task = asyncio.create_task(self._supervise(), name=f"whiskerless-{self.serial}")
        ready = asyncio.create_task(self._ready.wait())
        failed = asyncio.create_task(self._failed.wait())
        try:
            await asyncio.wait({ready, failed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            ready.cancel()
            failed.cancel()
        if self._ready.is_set():
            return
        # First attempt failed — stop the supervisor before surfacing the error so a
        # failed connect() doesn't leak a forever-retrying background task.
        await self.disconnect()
        raise self._first_error or WhiskerlessConnectionError(f"could not connect to {self.host}")

    async def disconnect(self) -> None:
        """Tear down the connection and its background task."""
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    def set_update_callback(self, callback: UpdateCallback | None) -> None:
        self._callback = callback

    @property
    def available(self) -> bool:
        return self._available

    @property
    def robot(self) -> LitterRobot4State:
        if self._robot is None:
            raise WhiskerlessConnectionError("no state received yet")
        return self._robot

    # --- supervised connection loop ------------------------------------------
    async def _supervise(self) -> None:
        backoff = 1.0
        # `while True` (not `while not self._closing`) so the flag isn't narrowed:
        # disconnect() flips it concurrently while this coroutine is awaiting.
        while True:
            if self._closing:
                break
            try:
                async with LitterRobot4Link(self._settings, self.serial) as link:
                    self._link = link
                    await link.request_state()
                    backoff = 1.0
                    if not self._available:
                        if self._ready.is_set():
                            log.info("Reconnected to Litter-Robot %s", self.serial)
                        self._available = True
                    self._ready.set()
                    async for message in link.messages():
                        self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # disconnect() cancels this task, so a close during reconnect arrives
                # as CancelledError above; everything else (incl. an unexpected bug)
                # logs and reconnects with backoff rather than leaving the robot
                # offline until the next reload.
                if not isinstance(exc, aiomqtt.MqttError | OSError | WhiskerlessError):
                    log.exception("Unexpected error in Litter-Robot %s supervisor", self.serial)
                self._link = None
                self._on_disconnect(exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_BACKOFF)
        self._link = None

    def _on_disconnect(self, exc: BaseException) -> None:
        if not self._ready.is_set() and self._first_error is None:
            self._first_error = _classify(exc)
            self._failed.set()  # unblock connect() so it can raise
        if self._available:
            log.warning("Lost connection to Litter-Robot %s: %s", self.serial, exc)
            self._available = False

    def _handle(self, message: StateMessage | ActivityMessage) -> None:
        if isinstance(message, StateMessage):
            self._robot = message.state
            self._state_updated.set()
            if self._callback is not None:
                try:
                    self._callback(message.state)
                except Exception:
                    log.exception("Litter-Robot %s update callback failed", self.serial)
        elif isinstance(message, ActivityMessage):
            # Telemetry between full states — prompt a throttled full refresh so
            # HA reflects the event promptly without spamming requestState.
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now - self._last_activity_refresh >= _ACTIVITY_REFRESH_THROTTLE and self._link is not None:
                self._last_activity_refresh = now
                task = loop.create_task(self._safe_request_state())
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

    async def _safe_request_state(self) -> None:
        link = self._link
        if link is None:
            return
        with contextlib.suppress(aiomqtt.MqttError, OSError):
            await link.request_state()

    # --- reads ---------------------------------------------------------------
    async def async_get_robot(self, *, timeout: float = 10.0) -> LitterRobot4State:
        """Prompt a fresh state and return it (heartbeat / after-write fetch)."""
        link = self._link
        if link is None:
            raise WhiskerlessConnectionError(f"not connected to {self.host}")
        self._state_updated.clear()
        await link.request_state()
        try:
            async with asyncio.timeout(timeout):
                await self._state_updated.wait()
        except TimeoutError:
            if self._robot is None:
                raise WhiskerlessConnectionError(f"no state from {self.host}") from None
        return self.robot

    async def async_get_serial(self) -> str:
        """Confirm the connection by fetching one state, then report the serial."""
        await self.async_get_robot()
        return self.serial

    # --- writes (publish → prompt → verify, with retry) ----------------------
    async def _write(
        self,
        command: Command,
        verify: StatePredicate,
        *,
        retries: int = 3,
        timeout: float = 8.0,
    ) -> None:
        link = self._link
        if link is None:
            raise WhiskerlessConnectionError(f"not connected to {self.host}")
        for attempt in range(max(1, retries)):
            await link.publish(command)
            try:
                state = await self.async_get_robot(timeout=timeout)
            except WhiskerlessConnectionError:
                continue
            if verify(state):
                return
            log.debug("%s not yet committed (attempt %d)", command.label, attempt + 1)
        raise WhiskerlessError(f"{command.label} did not commit after {retries} attempts")

    async def async_set_night_light_mode(self, mode: int) -> None:
        from .const import NIGHT_LIGHT_MODE

        expected = NIGHT_LIGHT_MODE.get(mode)
        await self._write(commands.set_night_light_mode(mode), lambda s: s.night_light_mode == expected)

    async def async_set_night_light_brightness(self, percent: int) -> None:
        await self._write(
            commands.set_night_light_brightness(percent),
            lambda s: s.night_light_brightness == percent,
        )

    async def async_set_clean_cycle_wait(self, minutes: int) -> None:
        await self._write(
            commands.set_clean_cycle_wait_minutes(minutes),
            lambda s: s.clean_cycle_wait_minutes == minutes,
        )

    async def async_set_keypad_lockout(self, enabled: bool) -> None:
        await self._write(commands.set_keypad_lockout(enabled), lambda s: s.keypad_lockout == enabled)

    async def async_set_panel_sleep_mode(self, enabled: bool) -> None:
        await self._write(commands.set_panel_sleep_mode(enabled), lambda s: s.panel_sleep_mode == enabled)

    async def async_set_weekday_sleep_enabled(self, enabled: bool) -> None:
        await self._write(
            commands.set_weekday_sleep_enabled(enabled),
            lambda s: s.weekday_sleep_enabled == enabled,
        )

    async def async_set_panel_brightness(self, percent: int) -> None:
        # One HA slider drives both the High and Low panel levels together.
        await self._write(
            commands.set_panel_brightness(percent, percent),
            lambda s: True,  # 0x0E is not echoed as a single named field; trust the write
            retries=1,
        )

    async def async_set_panel_sleep_time(self, minutes_since_midnight: int) -> None:
        await self._write(
            commands.set_panel_sleep_time(minutes_since_midnight),
            lambda s: s.panel_sleep_time == minutes_since_midnight,
        )

    async def async_set_panel_wake_time(self, minutes_since_midnight: int) -> None:
        await self._write(
            commands.set_panel_wake_time(minutes_since_midnight),
            lambda s: s.panel_wake_time == minutes_since_midnight,
        )

    async def async_start_clean_cycle(self) -> None:
        link = self._link
        if link is None:
            raise WhiskerlessConnectionError(f"not connected to {self.host}")
        await link.publish(commands.clean_cycle(), allow_motor=True)

    async def async_refresh(self) -> None:
        await self.async_get_robot()


def _classify(exc: BaseException) -> BaseException:
    text = str(exc).lower()
    if any(token in text for token in ("not authorized", "unauthorized", "bad user", "password")):
        return WhiskerlessAuthError(str(exc))
    if isinstance(exc, WhiskerlessError):
        return exc
    return WhiskerlessConnectionError(str(exc))
