"""One representative entity per platform decodes from the fixture correctly."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.litter_robot_4_status", "ready"),
        ("sensor.litter_robot_4_litter_level", "62"),
        ("sensor.litter_robot_4_waste_drawer_level", "35"),
        ("binary_sensor.litter_robot_4_waste_drawer_full", "off"),
        ("binary_sensor.litter_robot_4_cat_detected", "off"),
        ("select.litter_robot_4_night_light", "auto"),
        ("select.litter_robot_4_clean_cycle_wait_time", "15"),
        ("switch.litter_robot_4_control_lock", "off"),
        ("number.litter_robot_4_night_light_brightness", "50"),
        ("time.litter_robot_4_panel_sleep_time", "22:00:00"),
    ],
)
async def test_entity_states(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    entity_id: str,
    expected: str,
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert state.state == expected


async def test_clean_cycle_button_exists(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get("button.litter_robot_4_start_clean_cycle") is not None
