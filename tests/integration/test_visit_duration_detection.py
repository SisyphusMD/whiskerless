"""The visit-duration sensor enables itself once the robot reports one.

Register 0xBC is not optional hardware, it is an older-firmware gap: ESP 1.4.4
reports a duration at the end of every visit and 1.1.75 never has. A 12-hour
capture of a 1.1.75 robot logged five visits and three cat weights without a
single duration, and on 1.4.4 a weight is always accompanied by one — so on that
firmware the sensor would sit unknown for the life of the robot. It gets the same
treatment as the hopper entities instead.
"""

from __future__ import annotations

import json

import pytest
from custom_components.whiskerless.const import (
    CONF_VISIT_DURATION_LAST,
    CONF_VISIT_DURATION_SEEN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

DURATION_KEY = "last_visit_duration"
DURATION_ENTITY = "sensor.litter_robot_4_last_visit_duration"
# A 17-second visit: long enough that 1.4.4 would also have weighed the cat.
VISIT_ENDED = json.dumps({"type": "action", "data": ["0xBC0011"]})


def _disabled_by(registry: er.EntityRegistry) -> object:
    entity_id = registry.async_get_entity_id("sensor", "whiskerless", f"{MOCK_SERIAL}_{DURATION_KEY}")
    assert entity_id is not None, "the sensor should be registered either way"
    entry = registry.async_get(entity_id)
    assert entry is not None
    return entry.disabled_by


async def test_it_starts_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A 1.1.75 robot must not carry a sensor that can never have a value."""
    await setup_integration(hass, mock_config_entry, state_payload)

    assert _disabled_by(er.async_get(hass)) is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(DURATION_ENTITY) is None


async def test_a_duration_enables_it(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The first 0xBC switches it on, without a restart."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(VISIT_ENDED, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_VISIT_DURATION_SEEN] is True
    assert _disabled_by(er.async_get(hass)) is None


async def test_the_proving_reading_survives_the_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Enabling reloads the entry, so the duration is persisted with the flag.

    Without it the freshly enabled sensor would read unknown until the next cat,
    which can be hours away.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(VISIT_ENDED, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert hass.states.get(DURATION_ENTITY).state == "17"
    # And then discarded, so it cannot be re-applied on every future startup and
    # override whatever the sensor itself restored.
    assert CONF_VISIT_DURATION_LAST not in mock_config_entry.options


async def test_the_reload_does_not_reset_last_cat_visit(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """0xBC stamps last_cat_visit too, and that sensor is always enabled.

    Persisting only the duration left the enabling reload rebuilding the
    coordinator with no visit time, so an always-on sensor went back to unknown
    at the exact moment the robot had just told us a cat left. Its own restore
    cache is seconds too young to cover the gap.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(VISIT_ENDED, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_last_cat_visit")
    assert state is not None
    assert state.state not in ("unknown", "unavailable")


async def test_a_zero_second_visit_still_counts_as_proof(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """0 is the shortest real visit, not a missing reading.

    Gating detection on a truthy duration would leave a robot whose first
    reported visit was a hop-through disabled until the next one.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(json.dumps({"type": "action", "data": ["0xBC0000"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_VISIT_DURATION_SEEN] is True
    assert hass.states.get(DURATION_ENTITY).state == "0"


async def test_detection_is_remembered_across_restarts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A robot known to report durations does not re-disable the sensor."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_VISIT_DURATION_SEEN: True},
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert _disabled_by(er.async_get(hass)) is None


async def test_a_user_disabled_sensor_is_not_re_enabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Detection promotes integration-disabled entities, never overrides a user."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_{DURATION_KEY}",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_VISIT_DURATION_SEEN: True},
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert _disabled_by(registry) is er.RegistryEntryDisabler.USER


async def test_a_hopper_sighting_does_not_enable_it(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The two detections share a mechanism but not a verdict.

    A robot with a hopper on 1.1.75 is exactly the case where conflating them
    would put the permanently-unknown sensor back.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(
            json.dumps({"type": "action", "data": ["0x570014"]}),
            ACTIVITY_TOPIC,
        )
        await hass.async_block_till_done()

    assert CONF_VISIT_DURATION_SEEN not in mock_config_entry.options
    assert _disabled_by(er.async_get(hass)) is er.RegistryEntryDisabler.INTEGRATION
