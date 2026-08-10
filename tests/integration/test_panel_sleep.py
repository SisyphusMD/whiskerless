"""The panel sleep registers are computed by the firmware, not stored.

`isPanelSleepMode` (`0x1A`) tracks `weekdaySleepModeEnabled` and `panelSleepTime` /
`panelWakeTime` (`0x1B` / `0x1C`) mirror whichever weekday pair is in force today, so
writes to any of them are acknowledged and discarded. The schedule lives in
`0x1E`-`0x2B`.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import capture_writes, robot_online, setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

SWITCH = "switch.litter_robot_4_panel_sleep_mode"
SLEEP_TIME = "time.litter_robot_4_panel_sleep_time"


async def test_a_refused_sleep_mode_write_names_the_real_control(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot), pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
        )
    # Not the generic "did not commit", which sends people to the wrong setting.
    assert err.value.translation_key == "panel_sleep_not_writable"


async def test_the_schedule_is_written_to_every_weekday_register(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """0x1B is read-only, so a sleep time must land on 0x1E..0x2A instead."""
    doc = json.loads(state_payload)
    # What the robot will report back once all seven writes land.
    doc["panelSleepTime"] = 1290  # 21:30
    for day in ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"):
        doc[f"sleepTime{day}"] = 1290
    robot = await setup_integration(hass, mock_config_entry, json.dumps(doc))

    sent: list[str] = []
    with robot_online(robot):
        import custom_components.whiskerless.coordinator as coord

        original = coord.build_command_payload

        def spy(serial: str, code: str) -> str:
            sent.append(code)
            return original(serial, code)

        coord.build_command_payload = spy
        try:
            await hass.services.async_call(
                "time", "set_value", {"entity_id": SLEEP_TIME, "time": "21:30:00"}, blocking=True
            )
        finally:
            coord.build_command_payload = original

    writes = [c for c in sent if c.startswith("0x02")]
    # Sunday-first sleep registers: 0x1E, 0x20 … 0x2A. Never 0x1B.
    assert [c[:6] for c in writes if c[:6] != "0x02A0"] == [
        f"0x02{reg:02X}" for reg in range(0x1E, 0x2C, 2)
    ]
    assert all(c.endswith(f"{1290:04X}") for c in writes if c[:6] != "0x02A0")
    assert not any(c.startswith("0x021B") for c in sent), "0x1B is read-only"


async def test_a_write_transaction_is_not_interrupted_by_its_own_echoes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A schedule write must reach the robot as paced writes and nothing else.

    Every accepted register write echoes as an activity message, and an activity
    message normally schedules a requestState. Left ungated that refresh fires
    into the gap between two paced writes, recreating the back-to-back traffic
    that was seen dropping one write of seven.
    """
    doc = json.loads(state_payload)
    doc["panelSleepTime"] = 1290
    for day in ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"):
        doc[f"sleepTime{day}"] = 1290
    robot = await setup_integration(hass, mock_config_entry, json.dumps(doc))

    with robot_online(robot), capture_writes(robot, echo=True) as sent:
        await hass.services.async_call(
            "time",
            "set_value",
            {"entity_id": "time.litter_robot_4_panel_sleep_time", "time": "21:30:00"},
            blocking=True,
        )

    # Seven schedule writes then exactly one requestState — no echo-triggered extras.
    assert [c for c in sent if c.startswith("0x02A0")] == ["0x02A00000"]
    assert len([c for c in sent if not c.startswith("0x02A0")]) == 7
