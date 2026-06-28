"""Integration tests for the Whiskerless Home Assistant integration.

These run under ``pytest-homeassistant-custom-component`` (Python 3.13). The root
conftest skips this directory when Home Assistant is not installed so the
standalone library tests still run.
"""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from .const import STATE_TOPIC


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry, payload: str) -> None:
    """Add the entry, set it up, and feed an initial state document.

    Setup's first refresh publishes ``requestState`` and then *blocks* waiting for
    a pushed state, so we must deliver the reply while setup is parked — not after
    ``async_block_till_done`` (which would drain the parked task to its timeout
    first). Firing before the coordinator subscribes is a harmless no-op, so we
    keep firing until setup completes.
    """
    entry.add_to_hass(hass)
    setup_task = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
    for _ in range(50):
        if setup_task.done():
            break
        async_fire_mqtt_message(hass, STATE_TOPIC, payload)
        await asyncio.sleep(0)
    await setup_task
    await hass.async_block_till_done()
