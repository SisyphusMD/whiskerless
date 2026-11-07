"""Async Litter-Robot EVO link — connect, subscribe, send (guarded), confirm by echo.

Wraps an :class:`aiomqtt.Client` with the EVO's topic conventions and the EVO
safety guard on every publish. Writes are confirmed by their echo on activity,
which carries the value the robot applied. :meth:`read_all` reads every readable
register in one message, which is how a caller learns the robot's state on
connect, since the EVO has no state document.

The confirm and read helpers consume the shared message stream, so call them
sequentially rather than alongside a separate :meth:`messages` consumer on the
same link.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from dataclasses import replace
from types import TracebackType

import aiomqtt

from ...exceptions import WhiskerlessConnectionError
from ...mqtt import MqttSettings, create_client
from ...safety import assert_evo_sendable
from .codec import ActivityReading
from .commands import Command, read_all
from .const import READABLE_REGISTERS, TOPIC_PREFIX, command_topic, subscribe_topic
from .protocol import (
    ActivityMessage,
    EventMessage,
    PawprintMessage,
    build_command_payload,
    parse_message,
)

__all__ = ["LitterRobotEvoLink"]


class LitterRobotEvoLink:
    """A connected session to one EVO's broker."""

    def __init__(
        self,
        settings: MqttSettings,
        serial: str,
        *,
        topic_prefix: str = TOPIC_PREFIX,
        subscribe: bool = True,
    ) -> None:
        self.serial = serial
        self.topic_prefix = topic_prefix
        client_id = settings.client_id or f"whiskerless-{serial}"
        self._settings = replace(settings, client_id=client_id)
        self._client = create_client(self._settings)
        self._subscribe = subscribe

    @property
    def client(self) -> aiomqtt.Client:
        """The underlying aiomqtt client (for callers that need raw access)."""
        return self._client

    async def __aenter__(self) -> LitterRobotEvoLink:
        try:
            await self._client.__aenter__()
            if self._subscribe:
                await self._client.subscribe(
                    subscribe_topic(self.serial, prefix=self.topic_prefix), qos=1
                )
        except aiomqtt.MqttError as err:
            raise WhiskerlessConnectionError(
                f"cannot reach broker at {self._settings.host}:{self._settings.port} ({err})"
            ) from err
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def publish(self, command: Command, *, allow_dangerous: bool = False) -> None:
        """Send one command after the EVO safety guard approves it."""
        await self.publish_many([command], allow_dangerous=allow_dangerous)

    async def publish_many(
        self, commands: Sequence[Command], *, allow_dangerous: bool = False
    ) -> None:
        """Send several commands as one message, every one guarded first.

        The app writes multi-register settings (the sleep schedule) this way.
        Nothing is published unless every element passes the guard.
        """
        if not commands:
            return
        for command in commands:
            assert_evo_sendable(command.code, allow_dangerous=allow_dangerous)
        payload = build_command_payload(self.serial, *(command.code for command in commands))
        qos = 0 if any(command.at_most_once for command in commands) else 1
        await self._client.publish(
            command_topic(self.serial, prefix=self.topic_prefix), payload, qos=qos
        )

    async def publish_code(self, code: str, *, allow_dangerous: bool = False) -> None:
        """Send one raw ``0xTTBBRRVVVV`` element after the guard approves it."""
        assert_evo_sendable(code, allow_dangerous=allow_dangerous)
        await self._client.publish(
            command_topic(self.serial, prefix=self.topic_prefix),
            build_command_payload(self.serial, code),
            qos=1,
        )

    async def messages(self) -> AsyncGenerator[ActivityMessage | EventMessage | PawprintMessage]:
        """Yield parsed activity, event and pawprint messages as they arrive."""
        async for message in self._client.messages:
            parsed = parse_message(str(message.topic), message.payload)
            if parsed is not None:
                yield parsed

    async def apply(
        self, command: Command, *, timeout: float = 8.0, allow_dangerous: bool = False
    ) -> int | None:
        """Send ``command`` and return the value the robot echoes for its address.

        Returns ``None`` when no echo arrives within ``timeout``. The value can
        differ from the one written; the robot replaces a brightness level of 0
        with 50, for instance, and the echo is the only way to see that.
        """
        await self.publish(command, allow_dangerous=allow_dangerous)
        try:
            async with asyncio.timeout(timeout):
                async for message in self._client.messages:
                    parsed = parse_message(str(message.topic), message.payload)
                    if isinstance(parsed, ActivityMessage) and not parsed.query:
                        for reading in parsed.readings:
                            if reading.address == command.address:
                                return reading.value
        except TimeoutError:
            return None
        return None  # pragma: no cover - the message stream only ends with the connection

    async def read_all(self, *, timeout: float = 8.0) -> list[ActivityReading] | None:
        """Read every readable register and return the values the robot reports.

        Sends one message with a read of each address in ``READABLE_REGISTERS``
        and returns the readable elements of the ``query`` reply, in request
        order; fold them into a state with :func:`~.models.apply_message` or
        :meth:`~.models.LitterRobotEvoState.with_readings`. Returns ``None`` when
        no reply arrives within ``timeout``.
        """
        await self.publish_many(read_all())
        try:
            async with asyncio.timeout(timeout):
                async for message in self._client.messages:
                    parsed = parse_message(str(message.topic), message.payload)
                    if isinstance(parsed, ActivityMessage) and parsed.query:
                        readable = [
                            reading
                            for reading in parsed.readings
                            if reading.address in READABLE_REGISTERS
                        ]
                        if readable:
                            return readable
        except TimeoutError:
            return None
        return None  # pragma: no cover - the message stream only ends with the connection
