"""Cloud bridge: keep Whisker's cloud and app working for a robot on a local broker.

A re-provisioned robot talks only to your broker. The bridge connects to Whisker's
AWS IoT endpoint *as that robot*, using the robot's own cloud identity (the
certificate and key the Whisker app writes during onboarding), and relays MQTT
verbatim in both directions:

- cloud ``<cloud_prefix>/command``  → local ``<local_prefix>/command``
- local ``<local_prefix>/{activity,event,state}`` → cloud ``<cloud_prefix>/…``

The bridge never parses what it relays, so it works for any robot whiskerless
provisions; the two prefixes are the only per-device knowledge. It also exposes
every relayed message through a traffic hook, which makes the cloud's commands
readable in plaintext.

The local side is pluggable. :meth:`CloudBridge.run_local` opens its own client to
the local broker, and a host that already holds an MQTT connection (the Home
Assistant integration rides on Home Assistant's) feeds :meth:`CloudBridge.from_robot`
and passes a ``publish_local`` coroutine instead.

AWS IoT accepts one connection per client id, and the client id is the robot's
serial. The robot must therefore be off the cloud — re-provisioned onto the local
broker — before the bridge connects, or the two keep disconnecting each other.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias

import aiomqtt

from .exceptions import DangerousCommandError, ProtocolError, WhiskerlessConnectionError
from .mqtt import MqttSettings, create_client
from .safety import assert_sendable

#: The port AWS IoT serves MQTT over TLS with client certificates on.
CLOUD_PORT = 8883
#: The keepalive the robot's own firmware uses with the cloud.
CLOUD_KEEPALIVE = 120
#: Topics the robot publishes, relayed to the cloud.
ROBOT_TOPICS: tuple[str, ...] = ("activity", "event", "state")
#: Topics the cloud publishes for the robot, relayed to it.
CLOUD_TOPICS: tuple[str, ...] = ("command",)


class BridgeDirection(Enum):
    """Which way a message travels through the bridge."""

    TO_ROBOT = "to_robot"
    TO_CLOUD = "to_cloud"


@dataclass(frozen=True, slots=True)
class TopicMap:
    """The local and cloud topic prefixes of one robot.

    Prefixes are the topic up to and including the serial, without a trailing
    slash: ``prod/LR4/LR4C123456`` locally, ``prod/robots/LRE-…`` in the cloud,
    whatever each side was provisioned with.
    """

    local_prefix: str
    cloud_prefix: str
    robot_topics: tuple[str, ...] = ROBOT_TOPICS
    cloud_topics: tuple[str, ...] = CLOUD_TOPICS

    def __post_init__(self) -> None:
        for name, prefix in (("local", self.local_prefix), ("cloud", self.cloud_prefix)):
            if not prefix or prefix.endswith("/") or any(c in prefix for c in "#+"):
                raise ProtocolError(
                    f"{name} prefix {prefix!r} must be a topic without a trailing '/' or wildcards"
                )

    def local_subscriptions(self) -> list[str]:
        """Local topics to subscribe to for robot → cloud traffic."""
        return [f"{self.local_prefix}/{leaf}" for leaf in self.robot_topics]

    def cloud_subscriptions(self) -> list[str]:
        """Cloud topics to subscribe to for cloud → robot traffic."""
        return [f"{self.cloud_prefix}/{leaf}" for leaf in self.cloud_topics]

    def to_cloud(self, local_topic: str) -> str | None:
        """The cloud topic for a robot-published local topic, or ``None`` if unrelayed."""
        leaf = _leaf(local_topic, self.local_prefix)
        return f"{self.cloud_prefix}/{leaf}" if leaf in self.robot_topics else None

    def to_local(self, cloud_topic: str) -> str | None:
        """The local topic for a cloud-published topic, or ``None`` if unrelayed."""
        leaf = _leaf(cloud_topic, self.cloud_prefix)
        return f"{self.local_prefix}/{leaf}" if leaf in self.cloud_topics else None


def _leaf(topic: str, prefix: str) -> str | None:
    head, sep, leaf = topic.rpartition("/")
    return leaf if sep and head == prefix else None


@dataclass(frozen=True, slots=True)
class CloudIdentity:
    """The robot's Whisker cloud identity: trust anchor, certificate, private key."""

    root_ca_pem: str
    certificate_pem: str
    private_key_pem: str = field(repr=False)

    @classmethod
    def from_files(cls, root_ca: str | Path, certificate: str | Path, private_key: str | Path) -> CloudIdentity:
        """Read the three PEM files, refusing any that is empty or not PEM."""
        texts = []
        for label, path in (("root CA", root_ca), ("certificate", certificate), ("private key", private_key)):
            try:
                text = Path(path).read_text()
            except OSError as exc:
                raise WhiskerlessConnectionError(f"cannot read the cloud {label} at {path}: {exc}") from exc
            if "-----BEGIN " not in text:
                raise ProtocolError(f"the cloud {label} at {path} is not a PEM file")
            texts.append(text)
        return cls(*texts)


def cloud_settings(host: str, serial: str, identity: CloudIdentity) -> MqttSettings:
    """Connection settings that present ``identity`` to AWS IoT as robot ``serial``."""
    return MqttSettings(
        host=host,
        port=CLOUD_PORT,
        tls=True,
        ca_cert_data=identity.root_ca_pem,
        client_cert_data=identity.certificate_pem,
        client_key_data=identity.private_key_pem,
        client_id=serial,
        keepalive=CLOUD_KEEPALIVE,
    )


@dataclass(frozen=True, slots=True)
class BridgeTraffic:
    """One message the bridge relayed or sent."""

    direction: BridgeDirection
    topic: str
    payload: bytes
    at: datetime
    #: True for a message a person sent through :meth:`CloudBridge.send`, False for
    #: one relayed from the other side.
    injected: bool = False

    def text(self) -> str:
        """The payload as text, with undecodable bytes replaced."""
        return self.payload.decode(errors="replace")


def check_injected_command(payload: bytes, *, allow_untraced: bool = False) -> None:
    """Refuse a hand-written command for the robot unless the safety guard passes it.

    Commands the guard recognizes — a ``{"serial": …, "data": ["0x…", …]}`` object
    whose every element is a 10-character command element — go through
    :func:`~whiskerless.safety.assert_sendable` one by one, which refuses
    brick-class commands outright and untraced ones unless ``allow_untraced``.
    Anything the guard cannot read is untraced as a whole: refused unless
    ``allow_untraced``.
    """
    try:
        body: Any = json.loads(payload)
    except ValueError:
        body = None
    data = body.get("data") if isinstance(body, dict) else None
    elements = data if isinstance(data, list) and data and all(isinstance(e, str) for e in data) else None
    if elements is not None:
        try:
            for element in elements:
                assert_sendable(element, allow_dangerous=allow_untraced)
        except ProtocolError:
            pass  # not the guard's grammar: falls through to the untraced rule below
        else:
            return
    if not allow_untraced:
        raise DangerousCommandError(
            "the safety guard cannot classify this command; pass allow_untraced=True to send it anyway"
        )


PublishLocal: TypeAlias = Callable[[str, bytes], Awaitable[None]]
TrafficHook: TypeAlias = Callable[[BridgeTraffic], None]
ConnectionHook: TypeAlias = Callable[[bool], None]


class CloudBridge:
    """Relay one robot's MQTT between a local broker and Whisker's cloud."""

    def __init__(
        self,
        cloud: MqttSettings,
        topics: TopicMap,
        *,
        publish_local: PublishLocal | None = None,
        on_traffic: TrafficHook | None = None,
        on_connection: ConnectionHook | None = None,
        client_factory: Callable[[MqttSettings], aiomqtt.Client] = create_client,
    ) -> None:
        self.topics = topics
        self._cloud_settings = cloud
        self._publish_local = publish_local
        self._on_traffic = on_traffic
        self._on_connection = on_connection
        self._client_factory = client_factory
        self._cloud: aiomqtt.Client | None = None

    @property
    def connected(self) -> bool:
        """Whether the cloud connection is up."""
        return self._cloud is not None

    async def run(self) -> None:
        """Connect to the cloud and relay its commands until cancelled or disconnected.

        Raises :class:`WhiskerlessConnectionError` when the connection fails or
        drops; reconnecting is the caller's decision.
        """
        if self._publish_local is None:
            raise ProtocolError("run() needs publish_local; use run_local() to open a local client")
        try:
            async with self._client_factory(self._cloud_settings) as client:
                for topic in self.topics.cloud_subscriptions():
                    await client.subscribe(topic, qos=1)
                self._cloud = client
                if self._on_connection is not None:
                    self._on_connection(True)
                async for message in client.messages:
                    local = self.topics.to_local(str(message.topic))
                    if local is None:
                        continue
                    payload = _as_bytes(message.payload)
                    await self._publish_local(local, payload)
                    self._emit(BridgeDirection.TO_ROBOT, local, payload)
        except aiomqtt.MqttError as exc:
            raise WhiskerlessConnectionError(f"cloud connection failed: {exc}") from exc
        finally:
            was_connected, self._cloud = self._cloud is not None, None
            if was_connected and self._on_connection is not None:
                self._on_connection(False)

    async def run_local(self, local: MqttSettings) -> None:
        """Open a client to the local broker and run the bridge over it.

        Returns or raises when either side ends: a dropped connection on one side
        takes the other down with it, so the caller restarts both together.
        """
        previous = self._publish_local
        try:
            async with self._client_factory(local) as local_client:

                async def publish(topic: str, payload: bytes) -> None:
                    await local_client.publish(topic, payload, qos=1)

                async def pump() -> None:
                    async for message in local_client.messages:
                        await self.from_robot(str(message.topic), _as_bytes(message.payload))

                self._publish_local = publish
                for topic in self.topics.local_subscriptions():
                    await local_client.subscribe(topic, qos=1)
                tasks = {asyncio.create_task(pump()), asyncio.create_task(self.run())}
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                for task in done:
                    task.result()
        except aiomqtt.MqttError as exc:
            raise WhiskerlessConnectionError(f"local broker connection failed: {exc}") from exc
        finally:
            self._publish_local = previous

    async def from_robot(self, local_topic: str, payload: bytes) -> bool:
        """Relay one robot-published message to the cloud.

        Returns whether it was relayed: messages on topics outside the map, or
        arriving while the cloud is down, are dropped — the cloud would discard a
        stale report anyway, and the robot publishes again on its next change.
        """
        cloud_topic = self.topics.to_cloud(local_topic)
        if cloud_topic is None or self._cloud is None:
            return False
        await self._cloud.publish(cloud_topic, payload, qos=1)
        self._emit(BridgeDirection.TO_CLOUD, cloud_topic, payload)
        return True

    async def send(
        self,
        direction: BridgeDirection,
        payload: bytes,
        *,
        leaf: str | None = None,
        allow_untraced: bool = False,
    ) -> str:
        """Send a hand-written message toward the robot or the cloud; returns the topic.

        Toward the robot it goes to ``<local_prefix>/<leaf or command>`` after
        :func:`check_injected_command`. Toward the cloud it goes, as the robot, to
        ``<cloud_prefix>/<leaf or activity>``.
        """
        if direction is BridgeDirection.TO_ROBOT:
            check_injected_command(payload, allow_untraced=allow_untraced)
            if self._publish_local is None:
                raise WhiskerlessConnectionError("the bridge has no local connection")
            topic = f"{self.topics.local_prefix}/{leaf or self.topics.cloud_topics[0]}"
            await self._publish_local(topic, payload)
        else:
            if self._cloud is None:
                raise WhiskerlessConnectionError("the bridge is not connected to the cloud")
            topic = f"{self.topics.cloud_prefix}/{leaf or self.topics.robot_topics[0]}"
            await self._cloud.publish(topic, payload, qos=1)
        self._emit(direction, topic, payload, injected=True)
        return topic

    def _emit(self, direction: BridgeDirection, topic: str, payload: bytes, *, injected: bool = False) -> None:
        if self._on_traffic is not None:
            self._on_traffic(BridgeTraffic(direction, topic, payload, datetime.now(UTC), injected))


def _as_bytes(payload: object) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if payload is None:
        return b""
    if isinstance(payload, str):
        return payload.encode()
    return str(payload).encode()
