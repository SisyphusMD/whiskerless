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
from datetime import timedelta
from unittest.mock import patch

import custom_components.whiskerless.coordinator as coord
import pytest
from custom_components.whiskerless.const import (
    CONF_LEARNED_LITTER,
    CONF_LITTER_EMPTY_MM,
    CONF_LITTER_FULL_MM,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from whiskerless import WhiskerlessError

from . import (
    Robot,
    capture_writes,
    enable_calibration_buttons,
    robot_online,
    setup_integration,
)
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

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


async def test_a_missed_heartbeat_carries_the_last_known_signal(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Context for whoever reads the log: the last RSSI the robot reported before it
    went quiet. A hint, not a diagnosis — see backlog #21."""
    await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert "-54" in str(coordinator.last_exception)


async def test_a_robot_silent_from_the_start_reports_no_signal_it_never_learned(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """With no snapshot yet there is no RSSI to name, and the message must fall back
    rather than interpolate a placeholder it cannot fill."""
    await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data
    coordinator._robot = None

    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()

    assert "dBm" not in str(err.value)


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

    # And a well-formed message carrying a malformed element, which gets past the
    # parser's front door. The decoder rejects the element rather than raising, so
    # this never reaches the catch-all — worth pinning, because a decoder that
    # started raising here would take the subscription with it.
    robot.push(json.dumps({"type": "action", "data": ["010201"]}), ACTIVITY_TOPIC)
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
    [
        ("async_panel_reset", "0x02010401"),
        ("async_power_toggle", "0x02010101"),
        ("async_wifi_toggle", "0x02011001"),
    ],
)
async def test_a_press_with_no_lasting_trace_is_confirmed_by_its_echo(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    method: str,
    expected: str,
) -> None:
    """Reset from idle, Power and WiFi leave nothing in the state document.

    Reset only acknowledges an alarm, and a robot that is powered off or off the
    WiFi has left the network, so the echo is the only acknowledgement any of
    them can produce.
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
    enable_calibration_buttons(hass, mock_config_entry)
    await setup_integration(hass, mock_config_entry, state_payload)

    # Outside robot_online, so the fresh reading the button insists on never lands.
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.litter_robot_4_calibrate_full"},
            blocking=True,
        )

    assert err.value.translation_key == "litter_reading_unavailable"


def test_robot_helper_refuses_to_push_before_subscription() -> None:
    """Guards the test harness itself: a silent no-op here fakes a passing test."""
    with pytest.raises(AssertionError):
        Robot(payload="{}").push("{}")


async def test_a_malformed_message_does_not_break_the_subscription(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One unparseable payload must not cost the robot its live connection.

    The subscription is the integration's only source of state, and a decode is
    the one step handling a message that can raise on data nobody controls. If
    that escaped, a single malformed publish would leave the robot mute until
    Home Assistant restarted.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    # The decoder is defensive enough that malformed bytes come back as None
    # rather than raising, so the guard is here for a decode bug rather than for
    # bad input. Simulating one is the only way to exercise what it promises.
    with patch.object(coord, "parse_message", side_effect=ValueError("decode bug")):
        robot.push("{not json at all", ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert "Error handling MQTT message" in caplog.text

    # Still listening: a good state document after the bad one is still decoded.
    with robot_online(robot):
        robot.push(state_payload)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.litter_robot_4_status").state != STATE_UNAVAILABLE


async def test_shutdown_cancels_an_in_flight_refresh(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Unloading while a throttled refresh is queued must not leave it running.

    The refresh is fired as a background task, so an entry unloaded mid-flight
    would otherwise publish through a subscription that is already gone.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    # An activity message schedules the refresh task; do not let it finish.
    robot.push(json.dumps({"type": "action", "data": ["0x0B0016"]}), ACTIVITY_TOPIC)
    assert coordinator._tasks, "an activity message should queue a refresh"
    pending = next(iter(coordinator._tasks))

    await coordinator.async_shutdown()

    assert pending.cancelled() or pending.done()


async def test_a_firmware_update_refreshes_the_device_registry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Device info is registered when entities are added, so an OTA landing
    while the entry stayed loaded showed the old firmware until a reload."""


    robot = await setup_integration(hass, mock_config_entry, state_payload)
    doc = json.loads(state_payload)
    doc["espFirmware"] = "9.9.99"
    with robot_online(robot):
        robot.push(json.dumps(doc))
        await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={("whiskerless", MOCK_SERIAL)})
    assert device is not None
    assert device.sw_version == "9.9.99"


async def test_an_empty_cycle_with_no_odometer_baseline_trusts_the_echo(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """No baseline means the odometer cannot confirm anything either way.

    The fallback fetch used to run anyway and read as failure with the globe
    possibly dumping; with nothing to compare against, the echo is the only
    acknowledgement the press can have.
    """
    doc = json.loads(state_payload)
    del doc["odometerEmptyCycles"]
    robot = await setup_integration(hass, mock_config_entry, json.dumps(doc))
    coordinator = mock_config_entry.runtime_data

    with robot_online(robot), capture_writes(robot, echo=True) as sent:
        await coordinator.async_empty_cycle()

    assert sent.count("0x02010801") == 1


async def test_an_out_of_range_night_light_mode_verifies_as_its_clamped_self(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The builder clamps 7 to auto (2); verifying against the caller's 7 would
    report a clamped-but-applied write as a failure after three retries."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    with robot_online(robot), capture_writes(robot, echo=True) as sent:
        await coordinator.async_set_night_light_mode(7)

    assert sent.count("0x02180002") == 1  # written once: the verify passed


async def test_a_message_landing_mid_unload_is_dropped(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The MQTT unsubscribe runs after the platforms unload, so a message in
    that gap would fold state into a dying coordinator — or schedule a reload
    of an entry being removed."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data
    snapshot = coordinator.data.robot

    mock_config_entry.mock_state(hass, ConfigEntryState.UNLOAD_IN_PROGRESS)
    try:
        changed = json.loads(state_payload)
        changed["cleanCycleWaitTime"] = 12
        with robot_online(robot):
            robot.push(json.dumps(changed))
            await hass.async_block_till_done()
    finally:
        mock_config_entry.mock_state(hass, ConfigEntryState.LOADED)

    assert coordinator.data.robot is snapshot


async def test_the_learned_litter_low_survives_dedupe_and_drives_the_percentage(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The litter learner's coordinator wiring, pinned before Phase 2 moves it.

    Three claims: a state redelivery inside the dedupe window cannot corroborate
    the candidate it just created; two independent readings promote the learned
    fullest reading and persist it; and with no manual calibration that learned
    low anchors the percentage at 90.
    """

    # Without the firmware's own percentage, which always outranks the
    # calibrated approximation this test pins.
    doc = json.loads(state_payload)
    del doc["litterLevelPercentage"]
    payload = json.dumps(doc)
    enable_calibration_buttons(hass, mock_config_entry)
    robot = await setup_integration(hass, mock_config_entry, payload)  # 455 mm, ready
    coordinator = mock_config_entry.runtime_data

    learned = mock_config_entry.options[CONF_LEARNED_LITTER]
    assert learned["low"] is None and learned["low_candidate"] == 455

    with robot_online(robot):
        robot.push(payload)  # a QoS-1 redelivery, seconds later
        await hass.async_block_till_done()
    learned = mock_config_entry.options[CONF_LEARNED_LITTER]
    assert learned["low"] is None, "one reading must not corroborate itself"

    coordinator._derived.last_litter_sample_at -= timedelta(seconds=31)  # past the dedupe window
    with robot_online(robot):
        robot.push(payload)
        await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_LEARNED_LITTER]["low"] == 455

    state = hass.states.get("sensor.litter_robot_4_litter_level")
    assert state is not None
    assert state.state == "90"  # the learned fullest reading anchors 90%


async def test_two_point_calibration_yields_a_true_scale(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Both calibration buttons, pressed for real, produce the two-point scale.

    Each press stores the reading the robot sends AFTER the press — not the
    cached snapshot — and with both points stored the percentage is linear
    between them, no assumed slope.
    """


    doc = json.loads(state_payload)
    del doc["litterLevelPercentage"]  # the firmware's own percentage outranks calibration
    payload = json.dumps(doc)
    enable_calibration_buttons(hass, mock_config_entry)
    robot = await setup_integration(hass, mock_config_entry, payload)
    registry = er.async_get(hass)
    full = registry.async_get_entity_id(
        "button", "whiskerless", f"{MOCK_SERIAL}_calibrate_litter_full"
    )
    empty = registry.async_get_entity_id(
        "button", "whiskerless", f"{MOCK_SERIAL}_calibrate_litter_empty"
    )
    assert full is not None and empty is not None

    with robot_online(robot):
        robot.payload = json.dumps({**json.loads(payload), "litterLevel": 440})
        await hass.services.async_call("button", "press", {"entity_id": full}, blocking=True)
        robot.payload = json.dumps({**json.loads(payload), "litterLevel": 465})
        await hass.services.async_call("button", "press", {"entity_id": empty}, blocking=True)

    assert mock_config_entry.options[CONF_LITTER_FULL_MM] == 440
    assert mock_config_entry.options[CONF_LITTER_EMPTY_MM] == 465

    # Back at today's 455 mm, the two-point scale reads (465-455)/25 = 40%.
    with robot_online(robot):
        robot.push(payload)
        await hass.async_block_till_done()
    state = hass.states.get("sensor.litter_robot_4_litter_level")
    assert state is not None
    assert state.state == "40"


async def test_the_wifi_toggle_never_waits_for_an_echo_it_cannot_get(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A successful WiFi-off takes down the transport that would carry the echo.
    Waiting for one would report every success as a failure and invite a second
    press, which toggles the radio straight back on."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    with robot_online(robot), capture_writes(robot) as sent:   # no echo, deliberately
        await coordinator.async_wifi_toggle()

    assert sent.count("0x02011001") == 1
