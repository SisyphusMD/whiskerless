"""Integration tests for the Whiskerless Home Assistant integration.

These run under ``pytest-homeassistant-custom-component`` (Python 3.13). The root
conftest skips this directory when Home Assistant is not installed so the
standalone library tests still run.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from unittest.mock import patch

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import STATE_TOPIC


@dataclass
class Robot:
    """A stand-in robot that answers whatever the integration asks it.

    Tracks the LIVE subscription rather than a captured snapshot: reloading a
    config entry builds a fresh coordinator that subscribes again, and a reply
    delivered to the previous coordinator's callback reaches nobody.
    """

    payload: str
    _callback: Callable[[ReceiveMessage], None] | None = field(default=None, repr=False)

    def push(self, payload: str, topic: str = STATE_TOPIC) -> None:
        """Deliver a message as though the robot had published it."""
        assert self._callback is not None, "the integration has not subscribed yet"
        self._callback(ReceiveMessage(topic, payload, 1, False, topic, 0.0))


@contextlib.contextmanager
def robot_online(robot: Robot) -> Iterator[Robot]:
    """Answer every request the integration publishes, for as long as it is held.

    The coordinator's refresh clears its state event, publishes ``requestState``,
    then waits for a pushed state. Firing a reply blindly races that sequence and
    is wiped by the clear, which flaked on slow runners. Replying from the publish
    spy instead resolves the wait deterministically, exactly as the robot does.
    """
    real_subscribe = mqtt.async_subscribe

    async def _sub_spy(
        hass_: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        **kwargs: object,
    ) -> Callable[[], None]:
        unsub = await real_subscribe(hass_, topic, msg_callback, **kwargs)
        robot._callback = msg_callback
        return unsub

    async def _pub_spy(*_args: object, **_kwargs: object) -> None:
        if robot._callback is not None:
            robot.push(robot.payload)

    with (
        patch("custom_components.whiskerless.coordinator.mqtt.async_subscribe", _sub_spy),
        patch("custom_components.whiskerless.coordinator.mqtt.async_publish", _pub_spy),
    ):
        yield robot


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry, payload: str) -> Robot:
    """Set the entry up with a robot answering, and return it still armed.

    The returned Robot is NOT live once this call ends. Anything that makes the
    integration talk to the robot afterwards, including a reload triggered by
    enabling an entity, must run inside ``robot_online(robot)``.
    """
    entry.add_to_hass(hass)
    robot = Robot(payload=payload)
    with robot_online(robot):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return robot
