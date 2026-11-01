"""The whiskerless_alert events: what the notification blueprint listens for."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from custom_components import whiskerless as integration
from custom_components.whiskerless.alerts import alert_settings
from custom_components.whiskerless.const import (
    CONF_ACTIVE_ALERTS,
    CONF_ALERT_SETTINGS,
    CONF_LAST_VISIT,
    CONF_WEIGHT_HISTORY,
    DOMAIN,
    EVENT_ALERT,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from whiskerless.devices.litter_robot_4.alerts import AlertSettings

from . import Robot, robot_online, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

_real_sleep = asyncio.sleep


async def _no_wait(_: float) -> None:
    await _real_sleep(0)


def _doc(state_payload: str, **fields: object) -> str:
    return json.dumps({**json.loads(state_payload), **fields})


def _seen(events: list, alert: str) -> list[dict]:
    return [e.data for e in events if e.data["alert"] == alert]


async def test_a_condition_is_raised_once_and_cleared_once(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    events = async_capture_events(hass, EVENT_ALERT)

    with robot_online(robot):
        robot.push(_doc(state_payload, isDFIFull=1))
        robot.push(_doc(state_payload, isDFIFull=1))
        await hass.async_block_till_done()
    raised = _seen(events, "drawer_full")
    assert len(raised) == 1
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MOCK_SERIAL)})
    assert raised[0] == {
        "device_id": device.id,
        "serial": MOCK_SERIAL,
        "robot": device.name,
        "alert": "drawer_full",
        "event": "raised",
        "urgent": False,
        "message": "Waste drawer full. Empty it and press Reset.",
        "details": {},
    }
    assert mock_config_entry.options[CONF_ACTIVE_ALERTS] == ["drawer_full"]

    with robot_online(robot):
        robot.push(_doc(state_payload, isDFIFull=0))
        await hass.async_block_till_done()
    assert [e["event"] for e in _seen(events, "drawer_full")] == ["raised", "cleared"]
    assert mock_config_entry.options[CONF_ACTIVE_ALERTS] == []


async def test_an_alert_active_before_a_reload_is_not_announced_again(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, _doc(state_payload, isDFIFull=1))
    assert mock_config_entry.options[CONF_ACTIVE_ALERTS] == ["drawer_full"]
    events = async_capture_events(hass, EVENT_ALERT)
    with robot_online(robot):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert _seen(events, "drawer_full") == []


async def test_a_held_condition_is_raised_by_the_minute_tick(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Nothing new arrives while a bonnet sits off; the tick lets the hold elapse."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    events = async_capture_events(hass, EVENT_ALERT)
    robot.payload = _doc(state_payload, isBonnetRemoved=1)
    with robot_online(robot):
        robot.push(robot.payload)
        await hass.async_block_till_done()
        assert _seen(events, "bonnet_removed") == []

        # Only the publisher's clock jumps; the minute timer fires on the loop's. A
        # first bonnet sighting reloads the entry, and the new publisher starts the
        # hold afresh, so the clock moves twice.
        start = dt_util.utcnow()
        for step in (1, 2):
            later = start + step * timedelta(minutes=6)
            with patch("custom_components.whiskerless.alerts.dt_util.utcnow", return_value=later):
                async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
                await hass.async_block_till_done()
    raised = _seen(events, "bonnet_removed")
    assert [(e["event"], e["urgent"]) for e in raised] == [("raised", True)]


async def test_a_robot_that_stops_answering_is_reported_offline_after_the_hold(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    events = async_capture_events(hass, EVENT_ALERT)
    coordinator = mock_config_entry.runtime_data
    coordinator.async_set_update_error(TimeoutError("quiet"))
    await hass.async_block_till_done()
    assert _seen(events, "offline") == []

    # Only the publisher's clock moves: jumping the loop's would also run heartbeats
    # against a robot that is, by construction, not there.
    later = dt_util.utcnow() + timedelta(minutes=16)
    with patch("custom_components.whiskerless.alerts.dt_util.utcnow", return_value=later):
        coordinator.async_update_listeners()
    assert [e["message"] for e in _seen(events, "offline")] == ["Not responding for 15 minutes."]


async def test_visits_cycles_and_lock_changes_are_moments(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    events = async_capture_events(hass, EVENT_ALERT)
    with robot_online(robot), patch("custom_components.whiskerless.coordinator.asyncio.sleep", _no_wait):
        robot.push(_doc(state_payload, robotStatus=25, catDetect=3))
        robot.push(_doc(state_payload, robotStatus=7, catDetect=0))
        robot.push(json.dumps({"type": "action", "data": ["0x0903AC"]}), ACTIVITY_TOPIC)
        robot.push(_doc(state_payload, robotStatus=10))
        robot.push(_doc(state_payload, robotStatus=4, isKeypadLockout=1))
        await hass.async_block_till_done()

    visit = _seen(events, "visit")
    assert visit[0]["event"] == "moment"
    assert visit[0]["details"]["weight_lb"] == 9.4
    assert mock_config_entry.options[CONF_WEIGHT_HISTORY] == [9.4]
    assert CONF_LAST_VISIT in mock_config_entry.options
    assert [e["event"] for e in _seen(events, "cycle_completed")] == ["moment"]
    assert _seen(events, "panel_lock_changed")[0]["message"] == "Control lock turned on."


async def test_nothing_is_announced_before_home_assistant_has_started(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The automations that would hear it are not armed yet; it must not be lost."""
    hass.set_state(CoreState.not_running)
    events = async_capture_events(hass, EVENT_ALERT)
    await setup_integration(hass, mock_config_entry, _doc(state_payload, isDFIFull=1))
    assert _seen(events, "drawer_full") == []
    assert not mock_config_entry.options.get(CONF_ACTIVE_ALERTS)

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert [e["event"] for e in _seen(events, "drawer_full")] == ["raised"]


async def test_the_last_visit_survives_a_restart_for_the_no_visit_alert(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    mock_config_entry.add_to_hass(hass)
    last = dt_util.utcnow() - timedelta(hours=25)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_LAST_VISIT: last.isoformat()}
    )
    events = async_capture_events(hass, EVENT_ALERT)
    with robot_online(Robot(payload=state_payload)):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert [e["details"]["hours"] for e in _seen(events, "no_visit")] == [25]


async def test_a_robot_unreachable_at_setup_is_reported_offline_then_back(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A failed setup has no publisher, so the offline hold has to live outside one."""
    mock_config_entry.add_to_hass(hass)
    events = async_capture_events(hass, EVENT_ALERT)
    start = dt_util.utcnow()
    no_broker = patch.object(integration.coordinator.mqtt, "async_wait_for_mqtt_client", return_value=False)
    for minutes in (0, 16, 20):
        with no_broker, patch(
            "custom_components.whiskerless.alerts.dt_util.utcnow",
            return_value=start + timedelta(minutes=minutes),
        ):
            await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert [e["message"] for e in _seen(events, "offline")] == ["Not responding for 15 minutes."]
    assert mock_config_entry.options[CONF_ACTIVE_ALERTS] == ["offline"]

    with robot_online(Robot(payload=state_payload)):
        await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert [e["message"] for e in _seen(events, "offline")][1:] == ["Back online."]


async def test_the_options_page_sets_thresholds_and_keeps_everything_else(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    before = dict(mock_config_entry.options)

    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert flow["type"] is FlowResultType.FORM
    defaults = {key.schema: key.default() for key in flow["data_schema"].schema}
    assert defaults["deep_clean_days"] == 90

    chosen = {**defaults, "drawer_level_percent": 70.0}
    result = await hass.config_entries.options.async_configure(flow["flow_id"], chosen)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = mock_config_entry.options
    assert options[CONF_ALERT_SETTINGS]["drawer_level_percent"] == 70
    assert all(options[key] == value for key, value in before.items() if key != CONF_ALERT_SETTINGS)
    assert alert_settings(dict(options)).drawer_level_percent == 70


def test_stored_thresholds_that_no_longer_fit_are_ignored() -> None:
    stored = {CONF_ALERT_SETTINGS: {"filter_days": 14, "gone": 3, "deep_clean_days": "x", "no_visit_hours": 0}}
    assert alert_settings(stored) == AlertSettings(filter_days=14)
    assert alert_settings({}) == AlertSettings()
