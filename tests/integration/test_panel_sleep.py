"""Panel sleep mode is gated on the weekday schedule, so refuse it early.

The robot acknowledges `0x021A0001` while `weekdaySleepModeEnabled` is 0 and echoes
the register still at 0, which the verify loop can only report as a timeout naming
the wrong setting.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

ENTITY = "switch.litter_robot_4_panel_sleep_mode"


async def test_refused_while_the_weekday_schedule_is_off(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": ENTITY}, blocking=True
        )
    # Not "command_failed": the point is that it never reaches the robot.
    assert err.value.translation_key == "weekday_sleep_required"


async def test_allowed_once_the_weekday_schedule_is_on(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    doc = json.loads(state_payload)
    doc["weekdaySleepModeEnabled"] = 1
    doc["isPanelSleepMode"] = 1
    payload = json.dumps(doc)

    robot = await setup_integration(hass, mock_config_entry, payload)
    with robot_online(robot):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": ENTITY}, blocking=True
        )
    assert hass.states.get(ENTITY).state == "on"


async def test_turning_it_off_is_never_gated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Only enabling is conditional — an off write must stay reachable.

    Otherwise a robot left with sleep mode on and the weekday schedule off could
    never be turned back off from Home Assistant.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": ENTITY}, blocking=True
        )
    assert hass.states.get(ENTITY).state == "off"
