"""What the notification blueprint triggers on: the clean-cycle event, the
maintenance dates, and the cause carried by a globe-motor fault."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from custom_components.whiskerless.const import CONF_MAINTENANCE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration
from .const import ACTIVITY_TOPIC

CYCLE = "event.litter_robot_4_clean_cycle"
VISIT = "event.litter_robot_4_cat_visit"
DEEP_CLEAN = "date.litter_robot_4_last_deep_clean"
GLOBE = "binary_sensor.litter_robot_4_globe_motor_fault"

pytestmark = pytest.mark.usefixtures("mqtt_mock")


def _doc(state_payload: str, **fields: object) -> str:
    return json.dumps({**json.loads(state_payload), **fields})


def _activity(*codes: str) -> str:
    return json.dumps({"type": "action", "data": list(codes)})


async def test_a_cycle_ending_back_at_ready_fires_completed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(CYCLE).state == "unknown"

    with robot_online(robot):
        robot.push(_doc(state_payload, robotStatus=10, odometerCleanCycles=1285))
        await hass.async_block_till_done()
        assert hass.states.get(CYCLE).state == "unknown"
        robot.push(_doc(state_payload, robotStatus=4, odometerCleanCycles=1285, DFILevelPercent=41))
        await hass.async_block_till_done()

    fired = hass.states.get(CYCLE)
    assert fired.state != "unknown"
    assert fired.attributes["event_type"] == "completed"
    assert fired.attributes["cycle_count"] == 1285
    # From the document that ended the cycle, not the one before it.
    assert fired.attributes["waste_drawer_level"] == 41


async def test_ready_documents_alone_never_fire_it(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot):
        robot.push(_doc(state_payload, odometerCleanCycles=1290))
        await hass.async_block_till_done()
    assert hass.states.get(CYCLE).state == "unknown"


async def test_a_maintenance_date_is_kept_on_the_entry_and_survives_a_reload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(DEEP_CLEAN).state == "unknown"

    await hass.services.async_call(
        "date", "set_value", {"entity_id": DEEP_CLEAN, "date": "2026-10-15"}, blocking=True
    )
    assert hass.states.get(DEEP_CLEAN).state == "2026-10-15"
    assert mock_config_entry.options[CONF_MAINTENANCE] == {"last_deep_clean": "2026-10-15"}

    with robot_online(robot):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(DEEP_CLEAN).state == "2026-10-15"


async def test_an_unreadable_stored_date_reads_as_never_recorded(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_MAINTENANCE: {"last_deep_clean": "not a date", "last_globe_clean": 7}},
    )
    await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(DEEP_CLEAN).state == "unknown"
    assert hass.states.get("date.litter_robot_4_last_globe_clean").state == "unknown"
    assert mock_config_entry.runtime_data.maintenance_date("last_deep_clean") is None


async def test_a_globe_fault_names_its_reported_cause_while_held(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert "cause" not in hass.states.get(GLOBE).attributes

    with robot_online(robot):
        robot.push(_activity("0x350006"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    held = hass.states.get(GLOBE)
    assert held.state == "on"
    assert held.attributes["fault_code"] == 6
    assert held.attributes["cause"] == "pinch"

    with robot_online(robot):
        robot.push(_activity("0x350009"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get(GLOBE).attributes["cause"] == "unknown"

    with robot_online(robot):
        robot.push(_activity("0x350000"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    cleared = hass.states.get(GLOBE)
    assert cleared.state == "off"
    assert "cause" not in cleared.attributes


async def test_a_fault_raised_only_in_the_state_document_still_names_its_cause(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Firmware that populates the field turns the sensor on with no activity edge."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot):
        robot.push(_doc(state_payload, globeMotorFaultStatus=3))
        await hass.async_block_till_done()
    held = hass.states.get(GLOBE)
    assert held.state == "on"
    assert held.attributes["cause"] == "under_voltage"


_real_sleep = asyncio.sleep


async def _no_wait(_: float) -> None:
    """Skip the grace wait but still yield, as the real one does: Home Assistant
    starts tasks eagerly, so a sleep that never yields fires before the weight lands."""
    await _real_sleep(0)


async def test_a_visit_fires_with_the_weight_that_lands_just_after_it(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The weight arrives seconds after the sensors clear, so the event waits for it."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(VISIT).state == "unknown"

    with robot_online(robot), patch("custom_components.whiskerless.coordinator.asyncio.sleep", _no_wait):
        robot.push(_doc(state_payload, robotStatus=25, catDetect=3))
        robot.push(_doc(state_payload, robotStatus=7, catDetect=0))
        # Before the grace wait has run: the weight still counts.
        robot.push(_activity("0x0903AC"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    fired = hass.states.get(VISIT)
    assert fired.attributes["event_type"] == "visit"
    assert fired.attributes["weight_lb"] == 9.4
    assert isinstance(fired.attributes["duration_s"], int)


async def test_an_unweighed_visit_still_fires(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot), patch("custom_components.whiskerless.coordinator.asyncio.sleep", _no_wait):
        robot.push(_doc(state_payload, robotStatus=25, catDetect=1))
        robot.push(_doc(state_payload, robotStatus=7, catDetect=0))
        await hass.async_block_till_done()
    assert hass.states.get(VISIT).attributes["weight_lb"] is None
