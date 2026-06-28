"""Async Litter-Robot 4 link — connect, subscribe, send (guarded), verify.

Wraps an :class:`aiomqtt.Client` with the robot's topic conventions, the safety
guard on every publish, and the write→read-back→retry loop the firmware's
commit-latency quirk requires. The CLI drives a robot entirely through this; the
Home Assistant coordinator reuses the same primitives.

The verify/read helpers consume the shared message stream, so call them
sequentially (request/response style) rather than alongside a separate
:meth:`messages` consumer on the same link.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from types import TracebackType

import aiomqtt

from ...mqtt import MqttSettings, create_client
from ...safety import assert_sendable
from . import commands
from .commands import Command
from .const import command_topic, subscribe_topic
from .protocol import ActivityMessage, StateMessage, build_command_payload, parse_message


class LitterRobot4Link:
    """A connected session to one robot's broker."""

    def __init__(self, settings: MqttSettings, serial: str, *, subscribe: bool = True) -> None:
        self.serial = serial
        client_id = settings.client_id or f"whiskerless-{serial}"
        self._settings = replace(settings, client_id=client_id)
        self._client = create_client(self._settings)
        self._subscribe = subscribe

    @property
    def client(self) -> aiomqtt.Client:
        """The underlying aiomqtt client (for callers that need raw access)."""
        return self._client

    async def __aenter__(self) -> LitterRobot4Link:
        await self._client.__aenter__()
        if self._subscribe:
            await self._client.subscribe(subscribe_topic(self.serial), qos=1)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def publish(
        self,
        command: Command,
        *,
        allow_motor: bool = False,
        allow_dangerous: bool = False,
    ) -> None:
        """Send a command after the safety guard approves it."""
        assert_sendable(command.code, allow_motor=allow_motor, allow_dangerous=allow_dangerous)
        payload = build_command_payload(self.serial, command.code)
        await self._client.publish(command_topic(self.serial), payload, qos=1)

    async def request_state(self) -> None:
        """Ask the robot to publish its full state document."""
        await self.publish(commands.request_state())

    async def messages(self) -> AsyncIterator[StateMessage | ActivityMessage]:
        """Yield parsed state/activity events as they arrive."""
        async for message in self._client.messages:
            parsed = parse_message(str(message.topic), message.payload)
            if parsed is not None:
                yield parsed

    async def read_register(self, register: int, *, timeout: float = 8.0) -> int | None:
        """Type-1 read a register and return its value (or ``None`` on timeout)."""
        await self.publish(commands.read_register(register))
        try:
            async with asyncio.timeout(timeout):
                async for message in self._client.messages:
                    parsed = parse_message(str(message.topic), message.payload)
                    if isinstance(parsed, ActivityMessage):
                        for reading in parsed.readings:
                            if reading.register == register:
                                return reading.value
        except TimeoutError:
            return None
        return None

    async def apply_setting(
        self,
        command: Command,
        *,
        retries: int = 3,
        timeout: float = 8.0,
    ) -> bool:
        """Write a setting, read it back, and retry until it sticks.

        Mandatory for the time-of-day registers, which commit with variable
        latency; harmless (and good practice) for the rest. Returns whether the
        value was confirmed within ``retries`` attempts.
        """
        if command.register is None or command.value is None:
            raise ValueError("apply_setting requires a settings command with register + value")
        for _ in range(max(1, retries)):
            await self.publish(command)
            if await self.read_register(command.register, timeout=timeout) == command.value:
                return True
        return False
