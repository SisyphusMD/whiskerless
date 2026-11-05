"""The EVO link: guarded publishes and confirmation by echo."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import aiomqtt
import pytest

from whiskerless.devices.litter_robot_evo import commands
from whiskerless.devices.litter_robot_evo.link import LitterRobotEvoLink
from whiskerless.devices.litter_robot_evo.protocol import ActivityMessage, PawprintMessage
from whiskerless.exceptions import SafetyError, WhiskerlessConnectionError
from whiskerless.mqtt import MqttSettings

SERIAL = "LRE-01-40-01-2610-000000"
ACTIVITY = f"prod/robots/{SERIAL}/activity"


class _Message:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload.encode()


class FakeClient:
    """An aiomqtt.Client stand-in that echoes writes the way the robot does.

    ``echo`` maps a written value to the value the robot reports back; a value
    missing from it is echoed unchanged. ``silent`` makes the robot say nothing.
    """

    def __init__(self, *, echo: dict[int, int] | None = None, silent: bool = False,
                 fail_connect: bool = False) -> None:
        self.published: list[tuple[str, str, int]] = []
        self.subscribed: list[str] = []
        self._echo = echo or {}
        self._silent = silent
        self._fail_connect = fail_connect
        self.pending: asyncio.Queue[_Message] = asyncio.Queue()

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
        if self._silent:
            return
        # A read reply first, as noise: it names the address but must not count.
        for code in json.loads(payload)["data"]:
            address = code[4:8]
            value = int(code[8:12], 16)
            await self.pending.put(_Message(ACTIVITY, json.dumps({"type": "query", "data": [f"0x{address}0000"]})))
            echoed = self._echo.get(value, value)
            await self.pending.put(_Message(ACTIVITY, json.dumps({"type": "activity", "data": [f"0x{address}{echoed:04X}"]})))

    @property
    async def messages(self) -> AsyncIterator[_Message]:
        while True:
            yield await self.pending.get()


def _link(client: FakeClient, **kw: Any) -> LitterRobotEvoLink:
    with patch("whiskerless.devices.litter_robot_evo.link.create_client", return_value=client):
        return LitterRobotEvoLink(MqttSettings(host="192.0.2.10", port=8883), SERIAL, **kw)


async def test_it_subscribes_under_the_apps_prefix_by_default() -> None:
    client = FakeClient()
    async with _link(client) as link:
        assert link.client is client
    assert client.subscribed == [f"prod/robots/{SERIAL}/#"]


async def test_another_prefix_moves_every_topic() -> None:
    client = FakeClient(silent=True)
    async with _link(client, topic_prefix="prod/LR4") as link:
        await link.publish(commands.clean_cycle())
    assert client.subscribed == [f"prod/LR4/{SERIAL}/#"]
    assert client.published[0][0] == f"prod/LR4/{SERIAL}/command"


async def test_no_subscription_when_asked_not_to() -> None:
    client = FakeClient()
    async with _link(client, subscribe=False):
        pass
    assert client.subscribed == []


async def test_an_unreachable_broker_is_a_connection_error() -> None:
    with pytest.raises(WhiskerlessConnectionError, match="cannot reach broker"):
        async with _link(FakeClient(fail_connect=True)):
            pass


async def test_apply_returns_the_value_the_robot_echoes() -> None:
    link = _link(FakeClient())
    assert await link.apply(commands.set_panel_brightness(8, 1)) == 0x0801


async def test_apply_reports_a_substituted_value() -> None:
    """The echo is the only way to see the robot change what was written."""
    link = _link(FakeClient(echo={0x0801: 0x0832}))
    assert await link.apply(commands.set_panel_brightness(8, 1)) == 0x0832


async def test_apply_gives_up_on_a_silent_robot() -> None:
    link = _link(FakeClient(silent=True))
    assert await link.apply(commands.set_cycle_delay(7), timeout=0.05) is None


async def test_settings_publish_at_least_once_and_actions_at_most_once() -> None:
    client = FakeClient(silent=True)
    link = _link(client)
    await link.publish(commands.set_cycle_delay(7))
    await link.publish(commands.clean_cycle())
    assert [qos for _, _, qos in client.published] == [1, 0]


async def test_a_schedule_goes_out_as_one_message() -> None:
    client = FakeClient(silent=True)
    link = _link(client)
    await link.publish_many(commands.set_sleep_schedule(["sunday"], 0, 720))
    assert len(client.published) == 1
    assert len(json.loads(client.published[0][1])["data"]) == 15


async def test_publish_many_with_nothing_publishes_nothing() -> None:
    client = FakeClient(silent=True)
    await _link(client).publish_many([])
    assert client.published == []


async def test_one_refused_element_stops_the_whole_message() -> None:
    client = FakeClient(silent=True)
    link = _link(client)
    with pytest.raises(SafetyError):
        await link.publish_many([commands.set_cycle_delay(7), commands.power_off()])
    assert client.published == []
    await link.publish(commands.power_off(), allow_dangerous=True)
    assert len(client.published) == 1


async def test_a_raw_code_is_guarded() -> None:
    client = FakeClient(silent=True)
    link = _link(client)
    await link.publish_code("0x0202010808")
    with pytest.raises(SafetyError):
        await link.publish_code("0x0201010201")
    assert len(client.published) == 1


async def test_messages_yields_parsed_messages_and_skips_the_rest() -> None:
    client = FakeClient(silent=True)
    link = _link(client)
    await client.pending.put(_Message(f"prod/robots/{SERIAL}/command", '{"data": []}'))
    await client.pending.put(_Message(ACTIVITY, json.dumps({"type": "pawprint", "data": [{"type": "x"}]})))
    await client.pending.put(_Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01140001"]})))
    seen: list[Any] = []
    async for message in link.messages():
        seen.append(message)
        if len(seen) == 2:
            break
    assert isinstance(seen[0], PawprintMessage)
    assert isinstance(seen[1], ActivityMessage)


class _ScriptedClient(FakeClient):
    """Says nothing on publish; yields exactly the scripted messages, then ends."""

    def __init__(self, script: list[_Message]) -> None:
        super().__init__(silent=True)
        self._script = script

    @property
    async def messages(self) -> AsyncIterator[_Message]:
        for message in self._script:
            yield message


async def test_apply_waits_past_everything_that_is_not_its_echo() -> None:
    client = _ScriptedClient(
        [
            _Message(f"prod/robots/{SERIAL}/command", '{"data": ["0x0202090007"]}'),
            _Message(f"prod/robots/{SERIAL}/event", json.dumps({"type": "cycle", "data": ["0x02090003"]})),
            _Message(ACTIVITY, json.dumps({"type": "query", "data": ["0x02090000"]})),
            _Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01020016"]})),
            _Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01020032", "0x02090007"]})),
        ]
    )
    assert await _link(client).apply(commands.set_cycle_delay(7)) == 7


async def test_read_all_sends_one_message_and_returns_the_readable_values() -> None:
    client = _ScriptedClient(
        [
            _Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01020016"]})),
            _Message(ACTIVITY, json.dumps({"type": "query", "data": ["0x01020000"]})),
            _Message(
                ACTIVITY,
                json.dumps({"type": "query", "data": ["0x01030004", "0x01020000", "0x02090007"]}),
            ),
        ]
    )
    readings = await _link(client).read_all()
    assert readings is not None
    assert [(r.address, r.value) for r in readings] == [((0x01, 0x03), 4), ((0x02, 0x09), 7)]
    assert len(client.published) == 1
    sent = json.loads(client.published[0][1])["data"]
    assert sent == [c.code for c in commands.read_all()]


async def test_read_all_times_out_without_a_reply() -> None:
    assert await _link(FakeClient(silent=True)).read_all(timeout=0.01) is None


async def test_read_all_returns_none_when_the_stream_ends_without_a_reply() -> None:
    client = _ScriptedClient([_Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01140001"]}))])
    assert await _link(client).read_all(timeout=0.05) is None


async def test_messages_ends_with_the_stream() -> None:
    client = _ScriptedClient([_Message(ACTIVITY, json.dumps({"type": "activity", "data": ["0x01140001"]}))])
    assert len([m async for m in _link(client).messages()]) == 1
