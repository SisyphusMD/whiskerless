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
# A healthy 0x57 link report — the only event taken as proof a hopper exists.
# The dispense burst cannot serve: of two 1.1.75 robots that both carry a
# hopper, one emits it most cycles and the other never has.
LINK_REPORT = json.dumps({"type": "action", "data": ["0x570014"]})
# Link LAST on purpose: corroboration is computed over the whole message, so a
# dispense must be believed even when the 0x57 lands after it in the array.
LINKED_DISPENSE = json.dumps(
    {"type": "action", "data": ["0x0C0105", "0x0C103D", "0x0C2076", "0x570014"]}
)


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


async def test_a_link_report_enables_them(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """First healthy 0x57 report switches all four on, without a restart."""
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(LINK_REPORT, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_HOPPER_SEEN] is True
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is None, f"{key} should be enabled"


async def test_a_dispense_alone_does_not_enable_them(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The dispense burst is not evidence a hopper exists.

    Two 1.1.75 robots that both carry a hopper disagree completely — one emits
    the 0x0C burst most cycles, the other never has — so an uncorroborated burst
    must neither enable the entities nor record any hopper fact.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert not mock_config_entry.options.get(CONF_HOPPER_SEEN)
    data = mock_config_entry.runtime_data.data
    assert data.hopper_fill_raw is None
    assert data.last_hopper_dispensed is None
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION


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
        robot.push(LINKED_DISPENSE, ACTIVITY_TOPIC)
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
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )

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
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )

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
        mock_config_entry,
        options={**mock_config_entry.options, CONF_HOPPER_SEEN: True},
        pref_disable_new_entities=True,
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
    reading confirm itself within seconds and become a permanent anchor.

    The hopper is pre-armed so no detection reload interrupts the sequence; the
    persisted flag deliberately does not open the dispense gate (old rc builds
    set it from bare bursts), so a link report precedes the dispense here —
    which also exercises the prior-message half of the gate."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(LINK_REPORT, ACTIVITY_TOPIC)
        await hass.async_block_till_done()
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()
        # Several ordinary state refreshes, each carrying the retained value.
        for _ in range(4):
            robot.push(state_payload)
            await hass.async_block_till_done()

    learned = mock_config_entry.options.get("learned_hopper") or {}
    assert learned.get("low") is None, "one sample must not become an anchor"
    assert learned.get("low_candidate") == 0x03D


async def test_the_level_estimates_until_the_floor_is_learned(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Before the floor is proven, the level maps over the typical band, labelled.

    Per-unit floors vary, so this can be off by tens of points — hence the
    source attribute; the learned anchors are untouched by it.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_level",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_level",
    )
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        # Fill gauge 84: (84 - 66) / (90 - 66) = 75% of the typical band.
        robot.push(json.dumps({"type": "action", "data": ["0x570014", "0x0C1054"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_hopper_level")
    assert state is not None
    assert state.state == "75"
    assert state.attributes["source"] == "estimate"


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
