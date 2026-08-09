"""The optional LitterHopper enables its own entities once it reports."""

from __future__ import annotations

import json

import pytest
from custom_components.whiskerless.const import CONF_HOPPER_LAST, CONF_HOPPER_SEEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

HOPPER_ENTITIES = (
    ("binary_sensor", "hopper_connected"),
    ("binary_sensor", "hopper_empty"),
    ("sensor", "hopper_fill"),
    ("sensor", "last_hopper_dispensed"),
)

# A real dispense triple from a live capture. Phase 1 (0x0C103D) is the fill
# gauge reading 61, which on that robot was an empty hopper.
DISPENSE = json.dumps({"type": "action", "data": ["0x0C0105", "0x0C103D", "0x0C2076"]})


def _disabled_by(registry: er.EntityRegistry, domain: str, key: str) -> object:
    entity_id = registry.async_get_entity_id(domain, "whiskerless", f"{MOCK_SERIAL}_{key}")
    assert entity_id is not None, f"{key} should be registered either way"
    entry = registry.async_get(entity_id)
    assert entry is not None
    return entry.disabled_by


async def test_hopper_entities_start_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A robot without a hopper must not carry four permanently unknown entities."""
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION


async def test_a_dispense_enables_them(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """First hopper report switches all four on, without a restart."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_HOPPER_SEEN] is True
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is None, f"{key} should be enabled"


async def test_the_proving_reading_survives_the_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Enabling reloads the entry, so the readings are persisted with the flag.

    Without this the freshly enabled entities would read unknown until the next
    dispense, which can be several cycles away.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    # Served straight back by the coordinator the reload built, so the entity
    # shows a value the moment it appears rather than waiting for another cycle.
    assert mock_config_entry.runtime_data.data.hopper_fill_raw == 0x03D
    assert mock_config_entry.runtime_data.data.last_hopper_dispensed is not None
    # And then discarded: keeping it would re-apply this reading on every future
    # startup, overriding whatever the entities themselves restored.
    assert CONF_HOPPER_LAST not in mock_config_entry.options


async def test_detection_is_remembered_across_restarts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A robot known to have a hopper does not re-disable its entities."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_HOPPER_SEEN: True})

    await setup_integration(hass, mock_config_entry, state_payload)

    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is None


async def test_a_user_disabled_entity_is_not_re_enabled(
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
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_HOPPER_SEEN: True})

    await setup_integration(hass, mock_config_entry, state_payload)

    assert _disabled_by(registry, "sensor", "hopper_fill") is er.RegistryEntryDisabler.USER


async def test_the_disable_new_entities_preference_wins(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """That preference marks entries INTEGRATION-disabled too, so it looks the same
    as our own default; promoting anyway would override the user."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_HOPPER_SEEN: True}, pref_disable_new_entities=True
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    registry = er.async_get(hass)
    assert (
        _disabled_by(registry, "binary_sensor", "hopper_connected")
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_a_retained_reading_cannot_corroborate_itself(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The last gauge value is kept between dispenses, so learning must be driven
    by the dispense event. Sampling it on every heartbeat would let one bad
    reading confirm itself within seconds and become a permanent anchor."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()
        # Several ordinary state refreshes, each carrying the retained value.
        for _ in range(4):
            robot.push(state_payload)
            await hass.async_block_till_done()

    learned = mock_config_entry.options.get("learned_hopper") or {}
    assert learned.get("low") is None, "one sample must not become an anchor"
    assert learned.get("low_candidate") == 0x03D


async def test_an_unnamed_link_code_does_not_erase_a_known_connection(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """`0x57FFE2` (-30) is not a disconnect.

    It was captured repeating once a minute while the hopper was attached,
    dispensing and reporting a healthy gauge, then cleared on its own. Only
    `-15` is a proven disconnect; anything else unnamed leaves the last known
    state alone rather than describing a working hopper as unknown.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot):
        robot.push(json.dumps({"type": "action", "data": ["0x570001"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.litter_robot_4_hopper").state == "on"

    with robot_online(robot):
        robot.push(json.dumps({"type": "action", "data": ["0x57FFE2"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.litter_robot_4_hopper").state == "on"

    # -15 is proven, so it must still be believed.
    with robot_online(robot):
        robot.push(json.dumps({"type": "action", "data": ["0x57FFF1"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.litter_robot_4_hopper").state == "off"
