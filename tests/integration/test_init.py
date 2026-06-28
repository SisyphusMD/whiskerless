"""Setup / unload / push-update tests."""

from __future__ import annotations

import json

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from . import setup_integration
from .const import STATE_TOPIC

pytestmark = pytest.mark.usefixtures("mqtt_mock")

_DRAWER = "sensor.litter_robot_4_waste_drawer_level"


async def test_load_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(_DRAWER) is not None

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_push_updates_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(_DRAWER).state == "35"

    updated = json.loads(state_payload)
    updated["DFILevelPercent"] = 80
    async_fire_mqtt_message(hass, STATE_TOPIC, json.dumps(updated))
    await hass.async_block_till_done()

    assert hass.states.get(_DRAWER).state == "80"
