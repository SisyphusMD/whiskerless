"""The optional LitterHopper enables its own entities once it reports."""

from __future__ import annotations

import json

import pytest
from custom_components.whiskerless.const import (
    CONF_DERIVED,
    CONF_HOPPER_FILL_RAW,
    CONF_HOPPER_SEEN,
    CONF_LEARNED_HOPPER,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from whiskerless.devices.litter_robot_4.derive import Evidence

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
# A healthy 0x57 link report. Once treated as the only proof a hopper exists,
# now inert: positives arrive with the hopper sitting on a bench.
LINK_REPORT = json.dumps({"type": "action", "data": ["0x570014"]})
# A dispense that happens to carry a link code too. It must be believed on the
# strength of the burst alone, with the 0x57 neither helping nor hindering.
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


async def test_a_link_report_alone_does_not_enable_them(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """0x57 proves nothing, so it must not switch the entities on.

    A narrated session produced healthy positives while the hopper sat on the
    bench. Enabling four entities on that signal grows a hopper on a robot that
    has none.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(LINK_REPORT, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert not mock_config_entry.options.get(CONF_HOPPER_SEEN)
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION


async def test_a_dispense_enables_them(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Delivering litter is the only hopper evidence there is.

    0x57 used to gate this. That gate then discarded every fill sample on a
    robot which dispenses happily but rarely emits 0x57, leaving its hopper
    entities disabled indefinitely.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_HOPPER_SEEN] == str(Evidence.DISPENSE)
    data = mock_config_entry.runtime_data.data
    assert data.derived.hopper_fill_raw == 61
    assert data.derived.last_hopper_dispensed is not None
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is None, f"{key} should be enabled"


async def test_the_gauge_outlives_the_bootstrap(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The latest gauge is kept for good, and tracks every dispense.

    The derived snapshot is a one-shot that is dropped once the enabling reload
    has landed, so it cannot answer for the level after a restart. Dispensing is
    demand-driven and a well-fed robot can go days without one, which is long
    enough that the level would otherwise read unknown until it next runs low.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_HOPPER_FILL_RAW] == 61

    with robot_online(robot):
        robot.push(
            json.dumps({"type": "action", "data": ["0x0C0105", "0x0C1054", "0x0C2076"]}),
            ACTIVITY_TOPIC,
        )
        await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_HOPPER_FILL_RAW] == 84


def _enable_empty_alert(hass: HomeAssistant, entry: MockConfigEntry, **options: object) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE), **options}
    )
    er.async_get(hass).async_get_or_create(
        "binary_sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_empty",
        config_entry=entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_out_of_litter",
    )


# The signature of a floor confirmed across separate dispenses: low_hits at the
# HOPPER_EMPTY_CONFIRMATIONS threshold, exactly as the calibrator persists it.
CONFIRMED_FLOOR = {"low": 66, "high": 90, "low_candidate": None, "high_candidate": None, "low_hits": 3}


async def test_the_empty_alert_reports_ok_with_no_gauge(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A known hopper with no gauge yet has no evidence of a problem.

    Dispensing is demand-driven, so a hopper proven months ago can have no
    current reading; a PROBLEM sensor with nothing to go on says no-problem
    rather than parking on unknown or inventing a level.
    """
    _enable_empty_alert(hass, mock_config_entry)

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.runtime_data.data.derived.hopper_fill_raw is None
    state = hass.states.get("binary_sensor.litter_robot_4_hopper_out_of_litter")
    assert state is not None
    assert state.state == "off"


async def test_the_empty_alert_waits_for_this_units_own_floor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A gauge at the OLD fixed threshold proves nothing without a learned floor.

    Floors differ per unit — one robot's stocked phase-1 readings sit below
    another's empty flatline — so until this robot's floor is confirmed the
    alert stays quiet however low the number looks.
    """
    _enable_empty_alert(hass, mock_config_entry, **{CONF_HOPPER_FILL_RAW: 61})

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("binary_sensor.litter_robot_4_hopper_out_of_litter")
    assert state is not None
    assert state.state == "off"


async def test_the_empty_alert_fires_at_the_confirmed_floor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Gauge at the learned floor + confirmations = the flatline of a bare auger."""
    _enable_empty_alert(
        hass,
        mock_config_entry,
        **{CONF_HOPPER_FILL_RAW: 66, CONF_LEARNED_HOPPER: CONFIRMED_FLOOR},
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("binary_sensor.litter_robot_4_hopper_out_of_litter")
    assert state is not None
    assert state.state == "on"


async def test_the_empty_alert_clears_above_the_confirmed_floor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    _enable_empty_alert(
        hass,
        mock_config_entry,
        **{CONF_HOPPER_FILL_RAW: 84, CONF_LEARNED_HOPPER: CONFIRMED_FLOOR},
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("binary_sensor.litter_robot_4_hopper_out_of_litter")
    assert state is not None
    assert state.state == "off"


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
    assert mock_config_entry.runtime_data.data.derived.hopper_fill_raw == 0x03D
    assert mock_config_entry.runtime_data.data.derived.last_hopper_dispensed is not None
    # And then discarded: keeping it would re-apply this reading on every future
    # startup, overriding whatever the entities themselves restored.
    assert CONF_DERIVED not in mock_config_entry.options


async def test_detection_is_remembered_across_restarts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A robot known to have a hopper does not re-disable its entities.

    And it comes back with the gauge it last saw, rather than an unknown level
    until the robot next happens to run low enough to dispense.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            **mock_config_entry.options,
            CONF_HOPPER_SEEN: str(Evidence.DISPENSE),
            CONF_HOPPER_FILL_RAW: 84,
        },
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is None
    assert mock_config_entry.runtime_data.data.derived.hopper_fill_raw == 84


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
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)}
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
        options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)},
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
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)}
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
    assert learned.get("run_value") == 0x03D
    assert learned.get("run_length") == 1, "retained readings must not extend the run"


async def test_the_level_estimates_until_the_floor_is_learned(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Before the floor is proven, the level maps over the typical band, labelled.

    Per-unit floors vary, so this can be off by tens of points — hence the
    source attribute; the learned anchors are untouched by it.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)}
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
        robot.push(
            json.dumps({"type": "action", "data": ["0x0C0105", "0x0C1054", "0x0C2076"]}),
            ACTIVITY_TOPIC,
        )
        await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_hopper_level")
    assert state is not None
    assert state.state == "75"
    assert state.attributes["source"] == "estimate"


async def test_a_confirmed_floor_turns_the_estimate_into_a_measurement(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Once this unit's own floor is proven the level is its own scale, not a band."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            **mock_config_entry.options,
            CONF_HOPPER_SEEN: str(Evidence.DISPENSE),
            # Floor 61 confirmed across separate dispenses, ceiling 91.
            CONF_LEARNED_HOPPER: {"low": 61, "high": 91, "low_hits": 3},
        },
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_level",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_level",
    )
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        # Gauge 76 sits halfway up a 61-91 scale.
        robot.push(
            json.dumps({"type": "action", "data": ["0x0C0105", "0x0C104C", "0x0C2076"]}),
            ACTIVITY_TOPIC,
        )
        await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_hopper_level")
    assert state is not None
    assert state.state == "50"
    assert state.attributes["source"] == "measured"


async def test_no_0x57_code_moves_the_connected_sensor(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """0x57 is inert, including `-15`.

    `-15` was the one "proven" disconnect for months, then a narrated session
    produced it for merely opening the hopper's own drawer to refill it — with
    reattachment silent, so it would never clear. A dispense proves the hopper;
    nothing on this register may contradict that.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)
    with robot_online(robot):
        robot.push(DISPENSE, ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.litter_robot_4_hopper").state == "on"

    for code in ("0x570001", "0x57FFE2", "0x57FFF1", "0x57FFEF"):
        with robot_online(robot):
            robot.push(json.dumps({"type": "action", "data": [code]}), ACTIVITY_TOPIC)
            await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.litter_robot_4_hopper").state == "on", code


async def test_a_lone_0x0c_reading_is_not_a_dispense(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A type-1 read of 0x0C decodes to one HopperDispensed. It proves nothing.

    A real dispense is a burst of 2-3 phase-tagged codes; taking a single code as
    proof would let one diagnostic read grow four hopper entities on a robot that
    has none.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    with robot_online(robot):
        robot.push(json.dumps({"type": "action", "data": ["0x0C103D"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert not mock_config_entry.options.get(CONF_HOPPER_SEEN)
    data = mock_config_entry.runtime_data.data
    assert data.derived.hopper_fill_raw is None
    assert data.derived.hopper_connected is None
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION
