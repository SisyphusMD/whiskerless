"""Every writable platform reaches the wire with the register the robot expects.

The read paths were well covered and the write paths were not, which is the wrong
way round: a decode bug shows a wrong number, a write bug changes the robot. Each
case asserts the exact 10-character code, because a plausible-looking write to the
wrong register is precisely the failure this project has already shipped twice.

`robot_online` answers every publish with the same document, so a case must state
the value the robot will report *after* the write — otherwise the read-back never
verifies and the write retries until it gives up.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import capture_writes, robot_online, setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")


@pytest.mark.parametrize(
    ("committed", "domain", "service", "data", "expected"),
    [
        (
            {"cleanCycleWaitTime": 20},
            "number",
            "set_value",
            {"entity_id": "number.litter_robot_4_clean_cycle_wait_time", "value": 20},
            "0x02160014",
        ),
        (
            {"nightLightBrightness": 30},
            "number",
            "set_value",
            {"entity_id": "number.litter_robot_4_night_light_brightness", "value": 30},
            "0x0219001E",
        ),
        (
            {"isKeypadLockout": 1},
            "switch",
            "turn_on",
            {"entity_id": "switch.litter_robot_4_control_lock"},
            "0x02170001",
        ),
        (
            {"isKeypadLockout": 0},
            "switch",
            "turn_off",
            {"entity_id": "switch.litter_robot_4_control_lock"},
            "0x02170000",
        ),
        (
            {"nightLightMode": 0},
            "select",
            "select_option",
            {"entity_id": "select.litter_robot_4_night_light", "option": "off"},
            "0x02180000",
        ),
    ],
)
async def test_a_setting_write_lands_on_its_register(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    committed: dict[str, int],
    domain: str,
    service: str,
    data: dict[str, object],
    expected: str,
) -> None:
    doc = json.loads(state_payload)
    doc.update(committed)
    robot = await setup_integration(hass, mock_config_entry, json.dumps(doc))

    with robot_online(robot), capture_writes(robot) as sent:
        await hass.services.async_call(domain, service, data, blocking=True)

    assert expected in sent


PANEL_BRIGHT = "number.litter_robot_4_panel_brightness_bright_room"
PANEL_DARK = "number.litter_robot_4_panel_brightness_dark_room"


@pytest.mark.parametrize(
    ("entity_id", "value", "high", "low"),
    [(PANEL_BRIGHT, 60, 60, 40), (PANEL_DARK, 25, 60, 25)],
)
async def test_panel_brightness_writes_both_levels_in_one_packed_value(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    entity_id: str,
    value: int,
    high: int,
    low: int,
) -> None:
    """Register 0x0E packs both levels, so writing one must carry the other.

    Sending the changed level alone would zero the other one — each entity looks
    like it sets a single number, and the register does not work that way. Both
    directions are covered because they are separate functions, and the one that
    was not tested is the one that would silently blank the other level.
    """
    doc = json.loads(state_payload)
    doc["DisplayIntensityHigh"] = high
    doc["DisplayIntensityLow"] = low
    robot = await setup_integration(hass, mock_config_entry, json.dumps(doc))

    with robot_online(robot), capture_writes(robot) as sent:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
        )

    assert f"0x020E{(high << 8) | low:04X}" in sent


@pytest.mark.parametrize("entity_id", [PANEL_BRIGHT, PANEL_DARK])
async def test_panel_brightness_refuses_until_both_levels_are_known(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str, entity_id: str
) -> None:
    """The fixture reports neither level, which is a robot that has not said yet.

    Writing anyway would pack the unknown half as zero and blank the panel in the
    other ambient condition.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot), pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": 60}, blocking=True
        )


async def test_a_schedule_time_the_robot_has_not_reported_reads_unknown(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Minutes-since-midnight has no natural "absent", so out-of-range means absent.

    A robot with no schedule set reports a value outside 0–1439; rendering it
    anyway would put a fabricated bedtime on the dashboard.
    """
    doc = json.loads(state_payload)
    doc["panelSleepTime"] = 65535
    await setup_integration(hass, mock_config_entry, json.dumps(doc))

    state = hass.states.get("time.litter_robot_4_panel_sleep_time")
    assert state is not None
    assert state.state == "unknown"
