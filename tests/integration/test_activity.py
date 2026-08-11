"""The entities that exist only because of the activity stream.

None of these values appear in the state document, so nothing on the dashboard
moves unless an activity message is decoded and applied. That makes them the
easiest surface to break silently: the state tests keep passing while the visit
and drawer entities quietly stop updating.
"""

from __future__ import annotations

import json

import pytest
from custom_components.whiskerless.const import CONF_HOPPER_SEEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, seed_gated_sensors, setup_integration
from .const import ACTIVITY_TOPIC

pytestmark = pytest.mark.usefixtures("mqtt_mock")

LAST_VISIT = "sensor.litter_robot_4_last_cat_visit"
VISIT_DURATION = "sensor.litter_robot_4_last_visit_duration"
DRAWER_MOVED = "sensor.litter_robot_4_waste_drawer_last_moved"


def _activity(*codes: str) -> str:
    return json.dumps({"type": "action", "data": list(codes)})


async def test_a_visit_ending_stamps_the_time_and_the_duration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """0xBC closes a visit whether or not it was long enough to weigh the cat."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    # Absent, not unknown: ESP 1.1.75 never emits 0xBC, so the sensor ships
    # disabled and the first duration is what brings it into existence.
    assert hass.states.get(VISIT_DURATION) is None

    with robot_online(robot):
        robot.push(_activity(f"0xBC{30:04X}"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert hass.states.get(VISIT_DURATION).state == "30"
    # A timestamp sensor renders ISO-8601; only its presence is asserted, since
    # the value is "now" and pinning it would test the clock.
    assert hass.states.get(LAST_VISIT).state not in ("unknown", "unavailable")


async def test_a_hop_through_still_closes_the_visit(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A zero-second visit is the shortest real one, not a missing reading.

    It is also the case that produces no weight event at all, so the duration is
    the only evidence the cat was ever there.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(_activity("0xBC0000"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert hass.states.get(VISIT_DURATION).state == "0"


async def test_the_drawer_bay_records_that_it_moved(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """0x56 says the drawer moved and never which way, so it is a timestamp.

    Nine different codes turned up across removals and insertions alike, which is
    why this asserts only that any of them stamps the sensor.
    """
    seed_gated_sensors(hass, mock_config_entry)
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get(DRAWER_MOVED).state == "unknown"

    with robot_online(robot):
        robot.push(_activity("0x560001"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert hass.states.get(DRAWER_MOVED).state not in ("unknown", "unavailable")


async def test_the_first_dispense_cannot_corroborate_itself_across_the_reload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The sharpest version of the redelivery problem, and the one that shipped.

    The first believed dispense of a robot's life rides in with the 0x57 report
    that detects the hopper, which enables its entities and reloads the entry. A
    fresh coordinator starts with an open deduplication window, so a redelivery
    arriving in that gap — seconds after the original, exactly when one is most
    likely to still be in flight — used to count as a second dispense and anchor
    the empty floor on its own.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    dispense = _activity("0x570014", "0x0C0105", "0x0C103D", "0x0C2076")

    with robot_online(robot):
        robot.push(dispense, ACTIVITY_TOPIC)
        # Detection queues its own reload; blocking here runs it, which is the
        # gap a redelivery lands in. Reloading again by hand would not be that
        # sequence — the second pass drops the bootstrap that carries the window.
        await hass.async_block_till_done()
        robot.push(dispense, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    learned = mock_config_entry.options.get("learned_hopper") or {}
    assert learned.get("low") is None, "one physical dispense must not anchor the floor"


async def test_a_fault_the_robot_has_not_reported_is_not_reported_as_healthy(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Absent is not "no fault".

    Older firmware omits the field entirely, and defaulting it to off would put a
    confident green tick on a robot that has never said anything either way.
    """
    doc = json.loads(state_payload)
    doc.pop("globeMotorFaultStatus", None)
    await setup_integration(hass, mock_config_entry, json.dumps(doc))

    assert hass.states.get("binary_sensor.litter_robot_4_globe_motor_fault").state == "unknown"


async def test_a_redelivered_dispense_does_not_corroborate_itself(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The activity topic is QoS 1, so one dispense can arrive twice.

    Counting the redelivery would let a single low reading confirm an empty floor
    on its own, which is exactly what the corroboration requirement exists to
    prevent. Separate dispenses are cycles apart; redeliveries arrive at once.

    The hopper is already known here on purpose: the very first dispense of a
    robot's life also triggers detection, and the reload that follows builds a
    fresh coordinator, which would hide the deduplication being tested.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    # The 0x57 rides along because the persisted flag alone no longer opens the
    # dispense gate; the pre-armed option still keeps the detection reload away.
    dispense = _activity("0x570014", "0x0C0105", "0x0C103D", "0x0C2076")

    with robot_online(robot):
        for _ in range(2):
            robot.push(dispense, ACTIVITY_TOPIC)
            await hass.async_block_till_done()

    learned = mock_config_entry.options.get("learned_hopper") or {}
    assert learned.get("low") is None, "a redelivery must not corroborate its own reading"
    assert learned.get("low_candidate") == 0x03D
