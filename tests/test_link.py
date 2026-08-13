"""The CLI's transport, including its own copy of the commit-latency loop.

`apply_setting` and the Home Assistant coordinator's `_write_and_verify` solve
the same problem over different transports, and only one of them was tested. The
firmware quirk they exist for — a register that acknowledges a write and commits
it a moment later — is invisible to a test that assumes an obedient robot, so the
retry and give-up behaviour is pinned here the way it is on the coordinator side.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable
from typing import Any
from unittest.mock import patch

import aiomqtt
import pytest

from whiskerless.devices.litter_robot_4 import commands
from whiskerless.devices.litter_robot_4.const import Register
from whiskerless.devices.litter_robot_4.link import LitterRobot4Link
from whiskerless.exceptions import SafetyError, WhiskerlessConnectionError
from whiskerless.mqtt import MqttSettings

SERIAL = "LR4C000001"
ACTIVITY_TOPIC = f"prod/LR4/{SERIAL}/activity"


class _Message:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload.encode()


class FakeClient:
    """An aiomqtt.Client stand-in that answers reads from a scripted script.

    ``replies`` is consumed one entry per read: an int is echoed back as that
    register's value, and ``None`` means the robot stayed silent, which is what
    the read timeout is for.
    """

    def __init__(self, replies: Iterable[int | None] = (), *, fail_connect: bool = False) -> None:
        self.published: list[tuple[str, str, int]] = []
        self.subscribed: list[str] = []
        self._replies = list(replies)
        self._fail_connect = fail_connect
        self._pending: asyncio.Queue[_Message] = asyncio.Queue()

    async def __aenter__(self) -> FakeClient:
        if self._fail_connect:
            raise aiomqtt.MqttError("timed out")
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def subscribe(self, topic: str, **_: object) -> None:
        self.subscribed.append(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0, **_: object) -> None:
        self.published.append((topic, payload, qos))
        # Only a type-1 read draws an answer; a write is not echoed here, so a
        # read that follows a write picks up the next scripted reply.
        if not payload_is_read(payload) or not self._replies:
            return
        reply = self._replies.pop(0)
        if reply is not None:
            register = int(sent_code(payload)[4:6], 16)
            await self._pending.put(_Message(ACTIVITY_TOPIC, activity_json(register, reply)))

    @property
    async def messages(self) -> AsyncIterator[_Message]:
        while True:
            yield await self._pending.get()


def sent_code(payload: str) -> str:
    """The 10-character element out of a `…/command` payload."""
    return str(json.loads(payload)["data"][0])


def payload_is_read(payload: str) -> bool:
    return sent_code(payload).startswith("0x01")


def activity_json(register: int, value: int) -> str:
    return f'{{"type": "action", "data": ["0x{register:02X}{value:04X}"]}}'


def _link(client: FakeClient, **kw: Any) -> LitterRobot4Link:
    with patch(
        "whiskerless.devices.litter_robot_4.link.create_client", return_value=client
    ):
        return LitterRobot4Link(MqttSettings(host="192.0.2.10", port=8883), SERIAL, **kw)


async def test_a_setting_that_commits_immediately_is_written_once() -> None:
    client = FakeClient(replies=[20])
    link = _link(client)
    assert await link.apply_setting(commands.set_clean_cycle_wait_minutes(20)) is True
    writes = [p for _, p, _ in client.published if not payload_is_read(p)]
    assert len(writes) == 1


async def test_a_setting_that_commits_late_is_retried_until_it_sticks() -> None:
    """The whole reason this loop exists: the register lands after the read-back."""
    client = FakeClient(replies=[15, 20])  # still the old value, then the new one
    link = _link(client)
    assert await link.apply_setting(commands.set_clean_cycle_wait_minutes(20)) is True
    writes = [p for _, p, _ in client.published if not payload_is_read(p)]
    assert len(writes) == 2


async def test_a_setting_that_never_commits_reports_failure_without_hanging() -> None:
    """Returns False rather than raising: the CLI prints it, it is not a crash."""
    client = FakeClient(replies=[15, 15, 15])
    link = _link(client)
    assert await link.apply_setting(commands.set_clean_cycle_wait_minutes(20)) is False
    writes = [p for _, p, _ in client.published if not payload_is_read(p)]
    assert len(writes) == 3, "bounded at the retry count, like the coordinator"


async def test_a_command_with_nothing_to_read_back_is_refused() -> None:
    """Only a command carrying a register and value can be verified this way."""
    with pytest.raises(ValueError, match="register"):
        await _link(FakeClient()).apply_setting(commands.request_state())


async def test_a_silent_robot_times_out_rather_than_waiting_forever() -> None:
    client = FakeClient(replies=[None])
    link = _link(client)
    assert await link.read_register(Register.CLEAN_CYCLE_WAIT_TIME, timeout=0.05) is None


async def test_the_guard_stands_in_front_of_publish() -> None:
    """Every send goes through the chokepoint, including this transport's."""
    client = FakeClient()
    link = _link(client)
    with pytest.raises(SafetyError):
        await link.publish(commands.power_toggle())
    assert client.published == [], "a refused command must never reach the wire"


async def test_an_edge_triggered_press_is_published_at_most_once() -> None:
    """A redelivered press would run a second cycle; a lost one the user repeats."""
    client = FakeClient()
    link = _link(client)
    await link.publish(commands.clean_cycle())
    await link.request_state()

    (_, _, press_qos), (_, _, request_qos) = client.published
    assert press_qos == 0, "a press must not be redelivered"
    assert request_qos == 1, "an idempotent request should be at-least-once"


async def test_an_unreachable_broker_names_where_it_was_pointed() -> None:
    """aiomqtt says only "timed out", which reaches the CLI as a bare traceback."""
    link = _link(FakeClient(fail_connect=True))
    with pytest.raises(WhiskerlessConnectionError, match=re.escape("192.0.2.10:8883")):
        await link.__aenter__()


async def test_connecting_subscribes_to_the_robots_topics() -> None:
    client = FakeClient()
    async with _link(client):
        pass
    assert client.subscribed == [f"prod/LR4/{SERIAL}/#"]


async def test_subscription_can_be_declined_for_a_send_only_session() -> None:
    """`whiskerless send` publishes and leaves; a subscription would be noise."""
    client = FakeClient()
    async with _link(client, subscribe=False):
        pass
    assert client.subscribed == []


async def test_the_message_stream_yields_only_robot_events() -> None:
    """The command topic carries our own echo; yielding it would double-count."""
    client = FakeClient()
    link = _link(client)
    await client._pending.put(_Message(f"prod/LR4/{SERIAL}/command", '{"data": []}'))
    await client._pending.put(_Message(ACTIVITY_TOPIC, activity_json(0x16, 20)))

    stream = link.messages()
    first = await anext(stream)
    assert getattr(first, "readings", None), "the command echo should have been skipped"


def test_the_raw_client_is_reachable_for_callers_that_need_it() -> None:
    client = FakeClient()
    assert _link(client).client is client


def test_the_default_client_id_is_never_the_bare_serial() -> None:
    """Connecting AS the serial evicts the robot from its own broker session."""
    captured: list[MqttSettings] = []

    def create(settings: MqttSettings) -> FakeClient:
        captured.append(settings)
        return FakeClient()

    with patch("whiskerless.devices.litter_robot_4.link.create_client", side_effect=create):
        LitterRobot4Link(MqttSettings(host="192.0.2.10", port=8883), SERIAL)
    assert captured[0].client_id == f"whiskerless-{SERIAL}"
    assert captured[0].client_id != SERIAL


def test_a_caller_supplied_client_id_is_respected() -> None:
    captured: list[MqttSettings] = []

    def create(settings: MqttSettings) -> FakeClient:
        captured.append(settings)
        return FakeClient()

    with patch("whiskerless.devices.litter_robot_4.link.create_client", side_effect=create):
        LitterRobot4Link(
            MqttSettings(host="192.0.2.10", port=8883, client_id="mine"), SERIAL
        )
    assert captured[0].client_id == "mine"


async def test_a_read_ignores_echoes_for_other_registers() -> None:
    """The activity stream carries everything; only the asked-for one answers."""
    client = FakeClient()
    link = _link(client)
    await client._pending.put(_Message(ACTIVITY_TOPIC, activity_json(0x18, 2)))
    await client._pending.put(_Message(ACTIVITY_TOPIC, activity_json(0x16, 20)))
    assert await link.read_register(0x16, timeout=1) == 20


async def test_a_read_that_only_ever_hears_other_registers_times_out() -> None:
    client = FakeClient()
    link = _link(client)
    await client._pending.put(_Message(ACTIVITY_TOPIC, activity_json(0x18, 2)))
    assert await link.read_register(0x16, timeout=0.05) is None


async def test_a_read_survives_the_stream_ending_without_an_answer() -> None:
    """A dropped broker connection ends the stream; that is "no echo", not a crash."""

    class FiniteClient(FakeClient):
        @property
        async def messages(self) -> AsyncIterator[_Message]:
            yield _Message(ACTIVITY_TOPIC, activity_json(0x18, 2))

    link = _link(FiniteClient())
    assert await link.read_register(0x16, timeout=1) is None
