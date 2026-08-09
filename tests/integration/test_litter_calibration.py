"""Calibrating the litter percentage against this robot's own reference."""

from __future__ import annotations

import json

import pytest
from custom_components.whiskerless.const import CONF_LITTER_FULL_MM
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration
from .const import STATE_TOPIC

pytestmark = pytest.mark.usefixtures("mqtt_mock")

CALIBRATE = "button.litter_robot_4_calibrate_litter_filled_to_the_line"


def _message(payload: str) -> ReceiveMessage:
    return ReceiveMessage(STATE_TOPIC, payload, 1, False, STATE_TOPIC, 0.0)


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_pressing_calibrate_stores_the_current_distance(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The fixture reports 455 mm, which becomes this robot's reference."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        await _press(hass, CALIBRATE)

    assert mock_config_entry.options[CONF_LITTER_FULL_MM] == 455


async def test_calibration_is_refused_without_a_usable_reading(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Mid-cycle the ToF reads the rotating globe, so mm is suppressed.

    Capturing then would bake a garbage reference into the config entry.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    mid_cycle = json.dumps({**json.loads(state_payload), "robotStatus": 10, "litterLevel": 575})

    robot.payload = mid_cycle
    with robot_online(robot), pytest.raises(HomeAssistantError):
        await _press(hass, CALIBRATE)

    assert CONF_LITTER_FULL_MM not in mock_config_entry.options


async def test_calibration_takes_effect_immediately(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The press must move the sensor, not wait for the next heartbeat."""
    # The fixture reports a percentage, which outranks calibration; drop it so
    # the derived path is the one under test.
    raw = {k: v for k, v in json.loads(state_payload).items() if k != "litterLevelPercentage"}
    derived = json.dumps(raw)
    robot = await setup_integration(hass, mock_config_entry, derived)
    before = hass.states.get("sensor.litter_robot_4_litter_level")
    assert before is not None

    with robot_online(robot):
        await _press(hass, CALIBRATE)
    await hass.async_block_till_done()

    after = hass.states.get("sensor.litter_robot_4_litter_level")
    assert after is not None
    # 455 mm was just declared "at the line", which the cloud pins to 90%.
    assert after.state == "90"
    assert after.state != before.state


async def test_a_suppressed_reading_is_not_papered_over_by_the_last_one(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Mid-cycle the percentage must go unknown, not show a stale value."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get("sensor.litter_robot_4_litter_level").state == "62"

    mid_cycle = {**json.loads(state_payload), "robotStatus": 10, "litterLevel": 575}
    mid_cycle.pop("litterLevelPercentage", None)
    robot.push(json.dumps(mid_cycle))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_litter_level")
    assert state is not None
    assert state.state == "unknown"


async def test_the_reference_sensor_shows_the_press_landed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A button's only state is when it was last pressed, so success is
    otherwise indistinguishable from nothing happening."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    before = hass.states.get("sensor.litter_robot_4_litter_calibration_reference")
    assert before is not None
    assert before.state == "unknown"

    with robot_online(robot):
        await _press(hass, CALIBRATE)
    await hass.async_block_till_done()

    after = hass.states.get("sensor.litter_robot_4_litter_calibration_reference")
    assert after is not None
    assert after.state == "455"
