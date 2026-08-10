"""The paths that only run when the robot misbehaves.

Everything here is reachable in normal use — registers commit late, robots go
quiet, brokers arrive after Home Assistant does — but none of it happens in a
test that assumes a cooperative robot, which is how the largest module in the
integration ended up its least covered.

The real timeouts are seconds long by design. They are patched down rather than
waited out; what is under test is the retry and give-up behaviour, not the clock.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import custom_components.whiskerless.coordinator as coord
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from whiskerless import WhiskerlessError

from . import Robot, capture_writes, robot_online, setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

WAIT_TIME = "number.litter_robot_4_clean_cycle_wait_time"
# Register 0x16, twenty minutes — the fixture reports 15, so a robot left
# unmodified never satisfies the read-back.
WRITE_20 = "0x02160014"


@pytest.fixture(autouse=True)
def _impatient() -> None:
    """Collapse every wait so failure paths run at test speed.

    All four, not just the ones a given test looks like it needs: a press that is
    never acknowledged waits out _PRESS_TIMEOUT in full, and leaving it at five
    seconds puts that on the wall clock of every run.
    """
    with (
        patch.object(coord, "_VERIFY_TIMEOUT", 0.05),
        patch.object(coord, "_STATE_TIMEOUT", 0.05),
        patch.object(coord, "_PRESS_TIMEOUT", 0.05),
        patch.object(coord, "_WRITE_GAP", 0),
    ):
        yield


async def test_a_write_that_never_commits_gives_up_after_three_tries(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Bounded, and bounded at a number worth pinning.

    Unbounded retries would hammer a robot that is refusing the write, and one
    attempt would fail settings that legitimately commit late.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with (
        robot_online(robot),
        capture_writes(robot) as sent,
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": WAIT_TIME, "value": 20}, blocking=True
        )

    assert sent.count(WRITE_20) == 3


async def test_a_write_that_commits_late_still_succeeds(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The whole reason the retry exists: some registers land after the read-back."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    committed = json.loads(state_payload)
    committed["cleanCycleWaitTime"] = 20

    attempts = 0
    original = coord.build_command_payload

    def spy(serial: str, code: str) -> str:
        nonlocal attempts
        if code == WRITE_20:
            attempts += 1
            # Report the new value only from the second attempt onward.
            if attempts >= 2:
                robot.payload = json.dumps(committed)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        with robot_online(robot):
            await hass.services.async_call(
                "number", "set_value", {"entity_id": WAIT_TIME, "value": 20}, blocking=True
            )
    finally:
        coord.build_command_payload = original

    assert attempts == 2, "should have needed exactly one retry"
    assert hass.states.get(WAIT_TIME).state == "20"


async def test_a_robot_that_answers_nothing_marks_the_entry_unavailable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The heartbeat's only job — telemetry is push, so this is the liveness check."""
    await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    # Deliberately outside robot_online: the request goes out and nothing replies.
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert hass.states.get(WAIT_TIME).state == STATE_UNAVAILABLE


async def test_setup_waits_for_a_broker_instead_of_failing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Home Assistant starts its own MQTT integration on its own schedule.

    Treating "no broker yet" as a setup failure would leave the user to press
    Retry after every restart that happened to order the two the other way.
    """
    mock_config_entry.add_to_hass(hass)
    with patch.object(coord.mqtt, "async_wait_for_mqtt_client", return_value=False):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_an_undecodable_message_does_not_kill_the_subscription(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """One bad message must not deafen the integration until the next restart.

    The subscription callback is registered once; an exception escaping it takes
    every later message with it, including the good ones.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    robot.push("not json at all")
    await hass.async_block_till_done()

    doc = json.loads(state_payload)
    doc["cleanCycleWaitTime"] = 7
    robot.push(json.dumps(doc))
    await hass.async_block_till_done()

    assert hass.states.get(WAIT_TIME).state == "7"


async def test_unloading_takes_the_entities_with_it(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """An entity left behind keeps serving its last value forever.

    Deliberately not asserted by pushing a message after unload: ``Robot.push``
    calls the stored callback directly, so it would reach the old coordinator even
    if the unsubscribe worked, and a leak would pass just as happily.
    """
    await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(WAIT_TIME).state == "15"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    # Home Assistant keeps the row and marks it restored rather than deleting it;
    # what matters is that it stops reporting the last value it saw.
    state = hass.states.get(WAIT_TIME)
    assert state.state == STATE_UNAVAILABLE
    assert state.attributes["restored"] is True


@pytest.mark.parametrize(
    ("method", "expected"),
    [("async_panel_reset", "0x02010401"), ("async_power_toggle", "0x02010101")],
)
async def test_a_press_with_no_lasting_trace_is_confirmed_by_its_echo(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    method: str,
    expected: str,
) -> None:
    """Reset from idle and Power leave nothing in the state document to check.

    Reset only acknowledges an alarm, and a robot powered off has left the
    network, so the echo is the only acknowledgement either one can produce.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    with robot_online(robot), capture_writes(robot, echo=True) as sent:
        await getattr(coordinator, method)()

    assert sent.count(expected) == 1


async def test_the_empty_cycle_is_confirmed_by_its_own_odometer(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """There is no "emptying" status, so the count of empty cycles is the evidence."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    ran = json.loads(state_payload)
    ran["odometerEmptyCycles"] = 13
    original = coord.build_command_payload

    def spy(serial: str, code: str) -> str:
        if code == "0x02010801":
            robot.payload = json.dumps(ran)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        with robot_online(robot), capture_writes(robot, echo=True):
            await coordinator.async_empty_cycle()
    finally:
        coord.build_command_payload = original

    assert coordinator.data.robot.odometer_empty_cycles == 13


async def test_a_press_whose_echo_is_lost_falls_back_to_asking_the_robot(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A lost echo does not mean a lost press, and the press must not be repeated.

    So when there is something in the state document that proves the robot acted,
    it is asked rather than assumed — the alternative is a second empty cycle.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    ran = json.loads(state_payload)
    ran["odometerEmptyCycles"] = 13
    original = coord.build_command_payload
    presses = 0

    def spy(serial: str, code: str) -> str:  # deliberately never echoes
        nonlocal presses
        if code == "0x02010801":
            presses += 1
            robot.payload = json.dumps(ran)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        with robot_online(robot):
            await coordinator.async_empty_cycle()
    finally:
        coord.build_command_payload = original

    assert presses == 1, "the fallback must ask, never press again"
    assert coordinator.data.robot.odometer_empty_cycles == 13


async def test_a_press_with_nothing_to_check_and_no_echo_reports_failure(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Power leaves no trace to fall back on, so a lost echo is all there is.

    Reporting success would be a lie about a robot that may still be on, and
    pressing again could toggle it back — so it says it could not confirm.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    with (
        robot_online(robot),
        capture_writes(robot) as sent,  # no echo
        pytest.raises(WhiskerlessError),
    ):
        await coordinator.async_power_toggle()

    assert sent.count("0x02010101") == 1, "an unconfirmed press must never be repeated"


async def test_calibration_refuses_when_the_robot_will_not_answer(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Calibrating on a stale reading would bake a wrong reference in permanently."""
    await setup_integration(hass, mock_config_entry, state_payload)

    # Outside robot_online, so the fresh reading the button insists on never lands.
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.litter_robot_4_calibrate_litter_filled_to_the_line"},
            blocking=True,
        )

    assert err.value.translation_key == "litter_reading_unavailable"


def test_robot_helper_refuses_to_push_before_subscription() -> None:
    """Guards the test harness itself: a silent no-op here fakes a passing test."""
    with pytest.raises(AssertionError):
        Robot(payload="{}").push("{}")
