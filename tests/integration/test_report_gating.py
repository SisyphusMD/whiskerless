"""Event sensors gate on their first real report, and the upgrade sweep.

Observations vs capabilities: a sensor that exists before its fact has ever been
emitted is a permanent unknown on a robot that never emits it (0x56 only fires
on a drawer seat; one live robot has never emitted a weight). Controls
are exempt — their existence is the capability, not a report.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from custom_components.whiskerless.const import (
    CONF_CAT_VISIT_SEEN,
    CONF_DETECTION_RESET_BY,
    CONF_DRAWER_SEEN,
    CONF_HOPPER_FILL_RAW,
    CONF_HOPPER_SEEN,
    CONF_PET_WEIGHT_SEEN,
    CONF_VISIT_DURATION_SEEN,
    DETECTION_RESET_REVISION,
    DOMAIN,
)
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from . import robot_online, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

GATED = (
    ("sensor", "pet_weight"),
    ("sensor", "last_cat_visit"),
    ("sensor", "waste_drawer_last_moved"),
)


@pytest.fixture
def bare_config_entry() -> MockConfigEntry:
    """A fresh install: no sweep marker, nothing ever sighted."""
    return MockConfigEntry(
        domain=DOMAIN, title=MOCK_NAME, unique_id=MOCK_SERIAL, data=dict(MOCK_CONFIG)
    )


def _disabled_by(registry: er.EntityRegistry, domain: str, key: str) -> object:
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{MOCK_SERIAL}_{key}")
    assert entity_id is not None, f"{key} should be registered either way"
    entry = registry.async_get(entity_id)
    assert entry is not None
    return entry.disabled_by


def _activity(*codes: str) -> str:
    return json.dumps({"type": "action", "data": list(codes)})


async def test_event_sensors_start_disabled_on_a_fresh_install(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, bare_config_entry, state_payload)
    registry = er.async_get(hass)

    for domain, key in GATED:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION
    # The sweep ran once and marked itself done.
    assert bare_config_entry.options[CONF_DETECTION_RESET_BY] == DETECTION_RESET_REVISION


async def test_a_weight_event_enables_weight_and_visit(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """One 0x09 proves both the scale and the visit it measures."""
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    with robot_online(robot):
        robot.push(_activity("0x090329"), ACTIVITY_TOPIC)  # 809 raw = 8.09 lb
        await hass.async_block_till_done()

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] is True
    assert bare_config_entry.options[CONF_CAT_VISIT_SEEN] is True
    registry = er.async_get(hass)
    assert _disabled_by(registry, "sensor", "pet_weight") is None
    assert _disabled_by(registry, "sensor", "last_cat_visit") is None
    # The proving readings bridged the enabling reload.
    assert hass.states.get("sensor.litter_robot_4_pet_weight").state == "8.09"
    assert hass.states.get("sensor.litter_robot_4_last_cat_visit").state not in (
        "unknown",
        "unavailable",
    )


async def test_a_drawer_event_enables_the_drawer_sensor(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    with robot_online(robot):
        robot.push(_activity("0x560001"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert bare_config_entry.options[CONF_DRAWER_SEEN] is True
    registry = er.async_get(hass)
    assert _disabled_by(registry, "sensor", "waste_drawer_last_moved") is None
    assert hass.states.get("sensor.litter_robot_4_waste_drawer_last_moved").state not in (
        "unknown",
        "unavailable",
    )


async def test_an_occupancy_transition_enables_and_stamps_the_visit(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Some robots never emit a weight or duration; their visits are real anyway."""
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    occupied = json.dumps({**json.loads(state_payload), "catDetect": 1})
    with robot_online(robot):
        robot.push(occupied)
        await hass.async_block_till_done()

    assert bare_config_entry.options[CONF_CAT_VISIT_SEEN] is True
    assert er.async_get(hass) is not None
    assert _disabled_by(er.async_get(hass), "sensor", "last_cat_visit") is None
    assert hass.states.get("sensor.litter_robot_4_last_cat_visit").state not in (
        "unknown",
        "unavailable",
    )


async def test_a_first_document_arriving_mid_visit_is_not_an_arrival(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """None -> True proves presence, not a transition; only False -> True stamps."""
    occupied = json.dumps({**json.loads(state_payload), "catDetect": 1})
    await setup_integration(hass, bare_config_entry, occupied)

    assert CONF_CAT_VISIT_SEEN not in bare_config_entry.options


async def test_the_sweep_clears_an_unproven_hopper(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """rc.6 recorded hoppers from a dispense burst that proves no such thing.

    The flag is cleared and the entities go back to disabled; a real hopper
    re-proves itself the next time it delivers litter and re-enables.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry, options={CONF_HOPPER_SEEN: True}
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options
    assert bare_config_entry.options[CONF_DETECTION_RESET_BY] == DETECTION_RESET_REVISION
    assert _disabled_by(registry, "sensor", "hopper_fill") is er.RegistryEntryDisabler.INTEGRATION


async def test_the_sweep_seeds_gates_from_restored_reality(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A restored value is a real past report, so that sensor stays enabled."""
    bare_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_pet_weight",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_pet_weight",
    )
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_waste_drawer_last_moved",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_waste_drawer_last_moved",
    )
    mock_restore_cache(
        hass,
        (
            State("sensor.litter_robot_4_pet_weight", "8.8"),
            # The drawer sensor restored nothing real, so it is demoted.
            State("sensor.litter_robot_4_waste_drawer_last_moved", "unknown"),
        ),
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] is True
    assert _disabled_by(registry, "sensor", "pet_weight") is None
    assert CONF_DRAWER_SEEN not in bare_config_entry.options
    assert (
        _disabled_by(registry, "sensor", "waste_drawer_last_moved")
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_the_sweep_runs_once(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A marker from a previous run means armed flags are trusted, not re-swept."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.options[CONF_HOPPER_SEEN] is True


async def test_a_bit1_only_flap_is_not_a_visit(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """catDetect 2 (bit 1 alone) holds for hours with an empty globe on hopper
    robots; stamping it as a visit would invent one."""
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    phantom = json.dumps({**json.loads(state_payload), "catDetect": 2})
    with robot_online(robot):
        robot.push(phantom)
        await hass.async_block_till_done()

    assert CONF_CAT_VISIT_SEEN not in bare_config_entry.options
    assert hass.states.get("binary_sensor.litter_robot_4_cat_detected").state == "off"


async def test_one_message_proving_two_sensors_schedules_one_reload(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A first 0x09 proves the scale and the visit; each reload is a full
    unload/setup cycle, so they must coalesce."""
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    with (
        robot_online(robot),
        patch.object(
            hass.config_entries, "async_schedule_reload", wraps=hass.config_entries.async_schedule_reload
        ) as reload_spy,
    ):
        robot.push(json.dumps({"type": "action", "data": ["0x090329"]}), ACTIVITY_TOPIC)
        await hass.async_block_till_done()

    assert reload_spy.call_count == 1


async def test_the_sweep_accepts_native_evidence_behind_an_unavailable_state(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A robot offline at the last shutdown renders unavailable, but the restore
    extra data still holds the real weight — that is evidence, not absence."""
    bare_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_pet_weight",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_pet_weight",
    )
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_pet_weight", "unavailable"),
                SensorExtraStoredData(8.8, "lb").as_dict(),
            ),
        ),
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] is True
    assert _disabled_by(registry, "sensor", "pet_weight") is None


async def test_revision_2_retires_the_hopper_but_keeps_a_proven_duration(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Each revision only invalidates the evidence it actually changed.

    Revision 2 narrowed what proves a hopper and said nothing about durations, so
    an install swept under revision 1 must not lose a duration it earned — a quiet
    robot might not report another for a very long time.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={
            CONF_DETECTION_RESET_BY: True,  # the revision-1 marker
            CONF_HOPPER_SEEN: True,
            CONF_VISIT_DURATION_SEEN: True,
        },
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options
    assert bare_config_entry.options[CONF_VISIT_DURATION_SEEN] is True
    assert bare_config_entry.options[CONF_DETECTION_RESET_BY] == DETECTION_RESET_REVISION


async def test_a_downgrade_does_not_re_run_the_sweep(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A newer revision stored by a newer build must survive a downgrade.

    Re-running would strip a hopper that a later, stricter standard had already
    validated, and the user would have to wait out another dispense to get it back.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={
            CONF_DETECTION_RESET_BY: DETECTION_RESET_REVISION + 1,
            CONF_HOPPER_SEEN: True,
        },
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] is True
    assert bare_config_entry.options[CONF_DETECTION_RESET_BY] == DETECTION_RESET_REVISION + 1


async def test_a_globe_fault_on_the_activity_stream_alone_is_reported(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The state document does not mirror a globe-motor fault.

    A live robot raised 0x350001, held it 50 minutes and cleared it, while
    globeMotorFaultStatus read 0 in all 1198 state documents it published in that
    window — six of them sampled during the fault. A sensor reading only the
    field stayed off throughout.
    """
    robot = await setup_integration(hass, bare_config_entry, state_payload)
    entity = "binary_sensor.litter_robot_4_globe_motor_fault"
    assert hass.states.get(entity).state == "off"

    with robot_online(robot):
        robot.push(_activity("0x350001"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "on"

    # The state document keeps insisting there is no fault; it must not win.
    with robot_online(robot):
        robot.push(state_payload)
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "on"

    with robot_online(robot):
        robot.push(_activity("0x350000"), ACTIVITY_TOPIC)
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "off"


async def test_an_active_globe_fault_survives_a_reload(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The activity stream only speaks on the edges.

    The observed fault ran fifty minutes between raise and clear. A reload inside
    that window drops the latch, and the state document's cheerful 0 would then
    render a live fault as off.
    """
    entity = "binary_sensor.litter_robot_4_globe_motor_fault"
    bare_config_entry.add_to_hass(hass)
    mock_restore_cache(hass, (State(entity, "on"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert hass.states.get(entity).state == "on"


async def test_a_restored_fill_gauge_keeps_a_proven_hopper(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Only a dispense can produce that number, which is the standard of proof.

    Revision 2 cleared every hopper flag, and the replacement evidence is a
    dispense — which is demand-driven, so a robot sitting on its litter target
    can go weeks without one. That punished correct installs to fix wrong ones.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={CONF_DETECTION_RESET_BY: 2, CONF_HOPPER_SEEN: True},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_fill_raw",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_fill_raw", "84"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] is True
    assert _disabled_by(registry, "sensor", "hopper_fill") is None
    # The reading crosses too, not just the flag: the coordinator reads its gauge
    # from the option, so without this the level sensor comes back unknown while
    # the raw gauge beside it restores a real number.
    assert bare_config_entry.options[CONF_HOPPER_FILL_RAW] == 84


async def test_a_restored_link_state_does_not_keep_a_hopper(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """`hopper_connected` restoring `on` is the suspect evidence, not proof.

    That flag used to be granted by a 0x57 link report, and a positive arrives
    with the hopper sitting on a bench. Seeding from it would re-grant exactly
    what the sweep exists to retire.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={CONF_DETECTION_RESET_BY: 2, CONF_HOPPER_SEEN: True},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_connected",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper",
    )
    mock_restore_cache(hass, (State("binary_sensor.litter_robot_4_hopper", "on"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options
    assert _disabled_by(registry, "binary_sensor", "hopper_connected") is er.RegistryEntryDisabler.INTEGRATION


async def test_a_persisted_fill_gauge_also_keeps_the_hopper(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The same evidence, from the option rather than the restore cache.

    The restore cache expires; the persisted gauge does not, so a robot that has
    not dispensed in a long time still keeps the hopper it proved.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={CONF_DETECTION_RESET_BY: 2, CONF_HOPPER_FILL_RAW: 84},
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] is True


async def test_an_implausible_cached_gauge_is_not_proof(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A cache old enough to predate the multi-reading gate is not provenance.

    Those builds accepted a lone 0x0C as a dispense, and a diagnostic READ of that
    register produces one too. A real gauge lands in the calibrator's plausible
    band; a bare register echo need not.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={CONF_DETECTION_RESET_BY: 2, CONF_HOPPER_SEEN: True},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_fill_raw",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_fill_raw", "0"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options
