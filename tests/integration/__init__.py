"""Integration tests for the Whiskerless Home Assistant integration.

These run under ``pytest-homeassistant-custom-component`` (Python 3.13). The root
conftest skips this directory when Home Assistant is not installed so the
standalone library tests still run.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import STATE_TOPIC


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry, payload: str) -> None:
    """Set the entry up, simulating the robot answering ``requestState``.

    The coordinator's first refresh clears its state event, publishes
    ``requestState``, then waits for a pushed state. Firing the reply blindly
    races that sequence (and is wiped by the clear), which flaked on slow CI
    runners. Instead, capture the subscription callback and mock ``async_publish``
    to deliver the state document straight back — exactly as the robot answers a
    request — so the wait resolves deterministically every time.
    """
    entry.add_to_hass(hass)
    captured_cb: Callable[[ReceiveMessage], None] | None = None
    real_subscribe = mqtt.async_subscribe

    async def _sub_spy(
        hass_: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        **kwargs: object,
    ) -> Callable[[], None]:
        nonlocal captured_cb
        unsub = await real_subscribe(hass_, topic, msg_callback, **kwargs)
        captured_cb = msg_callback
        return unsub

    async def _pub_spy(*_args: object, **_kwargs: object) -> None:
        # The robot answers a command/request publish with a fresh state document.
        if captured_cb is not None:
            captured_cb(ReceiveMessage(STATE_TOPIC, payload, 1, False, STATE_TOPIC, 0.0))

    with (
        patch("custom_components.whiskerless.coordinator.mqtt.async_subscribe", _sub_spy),
        patch("custom_components.whiskerless.coordinator.mqtt.async_publish", _pub_spy),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
