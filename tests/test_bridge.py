"""The cloud bridge: topic mapping, the injected-command guard, and the relay loops."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import aiomqtt
import pytest

from whiskerless.bridge import (
    CLOUD_KEEPALIVE,
    CLOUD_PORT,
    BridgeDirection,
    BridgeTraffic,
    CloudBridge,
    CloudIdentity,
    TopicMap,
    _as_bytes,
    check_injected_command,
    cloud_settings,
)
from whiskerless.exceptions import (
    DangerousCommandError,
    NeverSendError,
    ProtocolError,
    WhiskerlessConnectionError,
)
from whiskerless.mqtt import MqttSettings

# Synthetic serials and prefixes; no real robot.
LOCAL = "prod/LR4/LR4C000001"
CLOUD = "prod/robots/LR4C000001"
TOPICS = TopicMap(LOCAL, CLOUD)
SETTINGS = MqttSettings(host="cloud.invalid")


class _Message:
    def __init__(self, topic: str, payload: object) -> None:
        self.topic = topic
        self.payload = payload


class FakeClient:
    """An aiomqtt.Client stand-in that yields scripted messages, then idles or ends.

    ``hold`` keeps the message stream open after the script runs out, the way a
    live connection does; without it the stream ends, as a dropped one does.
    """

    def __init__(
        self,
        script: Iterable[tuple[str, object]] = (),
        *,
        fail_connect: bool = False,
        hold: bool = False,
        fail_after: bool = False,
    ) -> None:
        self.published: list[tuple[str, object]] = []
        self.subscribed: list[str] = []
        self._script = list(script)
        self._fail_connect = fail_connect
        self._hold = hold
        self._fail_after = fail_after

    async def __aenter__(self) -> FakeClient:
        if self._fail_connect:
            raise aiomqtt.MqttError("connection refused")
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def subscribe(self, topic: str, **_: object) -> None:
        self.subscribed.append(topic)

    async def publish(self, topic: str, payload: object, **_: object) -> None:
        self.published.append((topic, payload))

    @property
    async def messages(self) -> AsyncIterator[_Message]:
        for topic, payload in self._script:
            await asyncio.sleep(0)
            yield _Message(topic, payload)
        if self._fail_after:
            raise aiomqtt.MqttError("connection lost")
        if self._hold:
            await asyncio.Event().wait()


def _factory(*clients: FakeClient):  # type: ignore[no-untyped-def]
    queue = list(clients)

    def make(_settings: MqttSettings) -> FakeClient:
        return queue.pop(0)

    return make


def _command(*codes: str) -> bytes:
    return json.dumps({"serial": "LR4C000001", "data": list(codes)}).encode()


# --- topic map ---------------------------------------------------------------


def test_topic_map_relays_robot_reports_to_the_cloud_and_commands_back() -> None:
    assert TOPICS.to_cloud(f"{LOCAL}/activity") == f"{CLOUD}/activity"
    assert TOPICS.to_cloud(f"{LOCAL}/state") == f"{CLOUD}/state"
    assert TOPICS.to_local(f"{CLOUD}/command") == f"{LOCAL}/command"


def test_topic_map_ignores_other_robots_and_other_directions() -> None:
    assert TOPICS.to_cloud(f"{LOCAL}/command") is None  # never echo a command back up
    assert TOPICS.to_cloud("prod/LR4/LR4C111111/activity") is None
    assert TOPICS.to_local(f"{CLOUD}/activity") is None
    assert TOPICS.to_local("command") is None


def test_topic_map_lists_its_subscriptions() -> None:
    assert TOPICS.local_subscriptions() == [f"{LOCAL}/activity", f"{LOCAL}/event", f"{LOCAL}/state"]
    assert TOPICS.cloud_subscriptions() == [f"{CLOUD}/command"]


@pytest.mark.parametrize("prefix", ["", "prod/LR4/", "prod/+/LR4C000001", "prod/#"])
def test_topic_map_refuses_malformed_prefixes(prefix: str) -> None:
    with pytest.raises(ProtocolError):
        TopicMap(prefix, CLOUD)
    with pytest.raises(ProtocolError):
        TopicMap(LOCAL, prefix)


# --- identity and settings ---------------------------------------------------


def _pem(label: str) -> str:
    return f"-----BEGIN {label}-----\nc3ludGhldGlj\n-----END {label}-----\n"


def test_identity_reads_three_pem_files(tmp_path: Path) -> None:
    for name, label in (("ca.pem", "CERTIFICATE"), ("dev.crt", "CERTIFICATE"), ("dev.key", "RSA PRIVATE KEY")):
        (tmp_path / name).write_text(_pem(label))
    identity = CloudIdentity.from_files(tmp_path / "ca.pem", tmp_path / "dev.crt", tmp_path / "dev.key")
    assert "PRIVATE KEY" in identity.private_key_pem
    assert "PRIVATE KEY" not in repr(identity)  # the key never reaches a log line


def test_identity_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(WhiskerlessConnectionError, match="root CA"):
        CloudIdentity.from_files(tmp_path / "nope", tmp_path / "nope", tmp_path / "nope")


def test_identity_refuses_a_file_that_is_not_pem(tmp_path: Path) -> None:
    (tmp_path / "ca.pem").write_text(_pem("CERTIFICATE"))
    (tmp_path / "dev.crt").write_text("not a certificate")
    with pytest.raises(ProtocolError, match="certificate"):
        CloudIdentity.from_files(tmp_path / "ca.pem", tmp_path / "dev.crt", tmp_path / "ca.pem")


def test_cloud_settings_present_the_robot_identity() -> None:
    identity = CloudIdentity(_pem("CERTIFICATE"), _pem("CERTIFICATE"), _pem("RSA PRIVATE KEY"))
    settings = cloud_settings("iot.invalid", "LR4C000001", identity)
    assert (settings.host, settings.port, settings.client_id) == ("iot.invalid", CLOUD_PORT, "LR4C000001")
    assert settings.keepalive == CLOUD_KEEPALIVE
    assert settings.verify_hostname is True
    assert settings.client_key_data == identity.private_key_pem


# --- the injected-command guard ----------------------------------------------


def test_guard_passes_a_recognized_safe_command() -> None:
    check_injected_command(_command("0x02010201"))  # clean cycle: SAFE


def test_guard_refuses_a_brick_class_command_even_when_untraced_is_allowed() -> None:
    with pytest.raises(NeverSendError):
        check_injected_command(_command("0x02A30000"), allow_untraced=True)


def test_guard_gates_a_recognized_dangerous_command() -> None:
    with pytest.raises(DangerousCommandError):
        check_injected_command(_command("0x02550001"))
    check_injected_command(_command("0x02550001"), allow_untraced=True)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        json.dumps({"type": "pawprint", "data": [{"type": "x"}]}).encode(),
        json.dumps({"serial": "LR4C000001", "data": []}).encode(),
        json.dumps(["0x02010201"]).encode(),
        _command("0x0202010808"),  # a 12-digit element: outside the guard's grammar
    ],
)
def test_guard_treats_unreadable_commands_as_untraced(payload: bytes) -> None:
    with pytest.raises(DangerousCommandError, match="allow_untraced"):
        check_injected_command(payload)
    check_injected_command(payload, allow_untraced=True)


# --- relaying ----------------------------------------------------------------


async def test_run_relays_cloud_commands_to_the_robot_and_reports_them() -> None:
    cloud = FakeClient([(f"{CLOUD}/command", b'{"data":["0x02010201"]}'), (f"{CLOUD}/other", b"x")])
    published: list[tuple[str, bytes]] = []
    seen: list[BridgeTraffic] = []

    async def publish_local(topic: str, payload: bytes) -> None:
        published.append((topic, payload))

    states: list[bool] = []
    bridge = CloudBridge(
        SETTINGS,
        TOPICS,
        publish_local=publish_local,
        on_traffic=seen.append,
        on_connection=states.append,
        client_factory=_factory(cloud),
    )
    await bridge.run()
    assert states == [True, False]
    assert cloud.subscribed == [f"{CLOUD}/command"]
    assert published == [(f"{LOCAL}/command", b'{"data":["0x02010201"]}')]
    assert [(t.direction, t.topic, t.injected) for t in seen] == [(BridgeDirection.TO_ROBOT, f"{LOCAL}/command", False)]
    assert seen[0].text() == '{"data":["0x02010201"]}'
    assert not bridge.connected  # the stream ended, so the connection is gone


async def test_run_needs_a_local_publisher() -> None:
    with pytest.raises(ProtocolError, match="publish_local"):
        await CloudBridge(SETTINGS, TOPICS, client_factory=_factory(FakeClient())).run()


async def test_run_turns_a_failed_connection_into_a_connection_error() -> None:
    async def publish_local(_topic: str, _payload: bytes) -> None:
        return None

    bridge = CloudBridge(
        SETTINGS, TOPICS, publish_local=publish_local, client_factory=_factory(FakeClient(fail_connect=True))
    )
    with pytest.raises(WhiskerlessConnectionError, match="cloud connection failed"):
        await bridge.run()


async def test_from_robot_drops_messages_while_the_cloud_is_down() -> None:
    bridge = CloudBridge(SETTINGS, TOPICS)
    assert await bridge.from_robot(f"{LOCAL}/activity", b"x") is False


async def test_run_local_relays_both_ways_until_one_side_ends() -> None:
    seen: list[BridgeTraffic] = []
    local = FakeClient([(f"{LOCAL}/activity", b"report"), (f"{LOCAL}/command", b"ignored")], hold=True)
    # The cloud stream yields once the local report has had a chance to pass, then drops.
    cloud = FakeClient([(f"{CLOUD}/command", "cmd")], fail_after=True)
    bridge = CloudBridge(SETTINGS, TOPICS, on_traffic=seen.append, client_factory=_factory(local, cloud))
    with pytest.raises(WhiskerlessConnectionError, match="cloud connection failed"):
        await bridge.run_local(MqttSettings(host="broker.invalid"))
    assert local.subscribed == TOPICS.local_subscriptions()
    assert (f"{LOCAL}/command", b"cmd") in local.published
    assert (f"{CLOUD}/activity", b"report") in cloud.published
    assert {t.direction for t in seen} == {BridgeDirection.TO_ROBOT, BridgeDirection.TO_CLOUD}


async def test_run_local_returns_when_the_local_stream_ends() -> None:
    local = FakeClient([])
    cloud = FakeClient([], hold=True)
    bridge = CloudBridge(SETTINGS, TOPICS, client_factory=_factory(local, cloud))
    await bridge.run_local(MqttSettings(host="broker.invalid"))


async def test_run_local_turns_a_failed_local_connection_into_a_connection_error() -> None:
    bridge = CloudBridge(SETTINGS, TOPICS, client_factory=_factory(FakeClient(fail_connect=True)))
    with pytest.raises(WhiskerlessConnectionError, match="local broker"):
        await bridge.run_local(MqttSettings(host="broker.invalid"))


# --- sending -----------------------------------------------------------------


async def test_send_to_robot_checks_the_command_and_publishes_locally() -> None:
    published: list[tuple[str, bytes]] = []
    seen: list[BridgeTraffic] = []

    async def publish_local(topic: str, payload: bytes) -> None:
        published.append((topic, payload))

    bridge = CloudBridge(SETTINGS, TOPICS, publish_local=publish_local, on_traffic=seen.append)
    topic = await bridge.send(BridgeDirection.TO_ROBOT, _command("0x02010201"))
    assert topic == f"{LOCAL}/command"
    assert published == [(topic, _command("0x02010201"))]
    assert seen[0].injected is True
    with pytest.raises(DangerousCommandError):
        await bridge.send(BridgeDirection.TO_ROBOT, b"raw")


async def test_send_to_robot_needs_a_local_connection() -> None:
    with pytest.raises(WhiskerlessConnectionError, match="local"):
        await CloudBridge(SETTINGS, TOPICS).send(BridgeDirection.TO_ROBOT, _command("0x02010201"))


async def test_send_to_cloud_needs_the_cloud_connection() -> None:
    with pytest.raises(WhiskerlessConnectionError, match="not connected"):
        await CloudBridge(SETTINGS, TOPICS).send(BridgeDirection.TO_CLOUD, b"{}")


async def test_send_to_cloud_publishes_as_the_robot() -> None:
    cloud = FakeClient([], hold=True)
    seen: list[BridgeTraffic] = []

    async def publish_local(_topic: str, _payload: bytes) -> None:
        return None

    up = asyncio.Event()
    bridge = CloudBridge(
        SETTINGS,
        TOPICS,
        publish_local=publish_local,
        on_traffic=seen.append,
        on_connection=lambda connected: up.set() if connected else None,
        client_factory=_factory(cloud),
    )
    task = asyncio.create_task(bridge.run())
    await up.wait()
    assert bridge.connected
    assert await bridge.from_robot(f"{LOCAL}/event", b"e") is True
    topic = await bridge.send(BridgeDirection.TO_CLOUD, b"{}", leaf="state")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert topic == f"{CLOUD}/state"
    assert cloud.published == [(f"{CLOUD}/event", b"e"), (f"{CLOUD}/state", b"{}")]
    assert [t.injected for t in seen] == [False, True]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [(b"b", b"b"), (bytearray(b"ba"), b"ba"), ("s", b"s"), (None, b""), (7, b"7")],
)
def test_payloads_normalize_to_bytes(payload: object, expected: bytes) -> None:
    assert _as_bytes(payload) == expected
