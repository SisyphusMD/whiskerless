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
    CONF_DRAWER_SEEN,
    CONF_HOPPER_FILL_RAW,
    CONF_HOPPER_SEEN,
    CONF_PET_WEIGHT_SEEN,
    CONF_VISIT_DURATION_SEEN,
    DOMAIN,
)
from custom_components.whiskerless.coordinator import SIGHTING_OPTIONS
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from whiskerless.devices.litter_robot_4.derive import Evidence

from . import restore_latching_sensor, robot_online, setup_integration
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


# What a change to ACCEPTED_EVIDENCE leaves behind: a sighting recorded against
# evidence this capability no longer accepts (a weight proves a scale, never a
# hopper). Nothing else makes the re-examination run.
RETIRED = str(Evidence.CAT_WEIGHT)

# The retired global re-sweep counter, which this build reads once (to see which
# one-off sweeps an install ran) and then drops.
_RESET_MARKER = "detection_reset_by"


async def test_event_sensors_start_disabled_on_a_fresh_install(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    await setup_integration(hass, bare_config_entry, state_payload)
    registry = er.async_get(hass)

    for domain, key in GATED:
        assert _disabled_by(registry, domain, key) is er.RegistryEntryDisabler.INTEGRATION
    # And nothing was recorded as proven, since nothing has reported.
    assert not any(key in bare_config_entry.options for key in SIGHTING_OPTIONS.values())


async def test_a_weight_event_enables_weight_and_visit(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """One 0x09 proves both the scale and the visit it measures."""
    robot = await setup_integration(hass, bare_config_entry, state_payload)

    with robot_online(robot):
        robot.push(_activity("0x090329"), ACTIVITY_TOPIC)  # 809 raw = 8.09 lb
        await hass.async_block_till_done()

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] == str(Evidence.CAT_WEIGHT)
    assert bare_config_entry.options[CONF_CAT_VISIT_SEEN] == str(Evidence.CAT_WEIGHT)
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

    assert bare_config_entry.options[CONF_DRAWER_SEEN] == str(Evidence.DRAWER_MOVED)
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

    assert bare_config_entry.options[CONF_CAT_VISIT_SEEN] == str(Evidence.OCCUPANCY)
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
        bare_config_entry, options={CONF_HOPPER_SEEN: RETIRED}
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
    assert _disabled_by(registry, "sensor", "hopper_fill") is er.RegistryEntryDisabler.INTEGRATION


async def test_a_restored_duration_is_never_enough_to_re_prove_one(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The evidence table decides what a recovered value is worth, and a
    restored duration is worth nothing: the builds that recorded one did so from
    evidence since proven wrong, so the sensor waits for a live 0xBC."""
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry, options={CONF_VISIT_DURATION_SEEN: RETIRED}
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_last_visit_duration",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_last_visit_duration",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_last_visit_duration", "17"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_VISIT_DURATION_SEEN not in bare_config_entry.options
    assert (
        _disabled_by(er.async_get(hass), "sensor", "last_visit_duration")
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_a_sighting_nobody_wrote_down_is_recovered_from_a_real_report(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """An install from before sightings existed keeps what it genuinely earned.

    Its entities are gated on a record it never wrote, so without this a robot
    that has been reporting weights for months would go back to hiding the
    sensor until the next cat. A restored value is that record; an unknown one
    is not, and stays gated until the robot reports for real.
    """
    bare_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, object_id in (
        ("pet_weight", "litter_robot_4_pet_weight"),
        ("waste_drawer_last_moved", "litter_robot_4_waste_drawer_last_moved"),
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{MOCK_SERIAL}_{key}",
            config_entry=bare_config_entry,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            suggested_object_id=object_id,
        )
    mock_restore_cache(
        hass,
        (
            State("sensor.litter_robot_4_pet_weight", "8.8"),
            # The drawer sensor restored nothing real, so it proves nothing.
            State("sensor.litter_robot_4_waste_drawer_last_moved", "unknown"),
        ),
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] == str(Evidence.RESTORED)
    assert _disabled_by(registry, "sensor", "pet_weight") is None
    assert CONF_DRAWER_SEEN not in bare_config_entry.options
    assert (
        _disabled_by(registry, "sensor", "waste_drawer_last_moved")
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_a_sighting_the_old_sweeps_already_validated_is_labelled_not_retired(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """It was re-derived by the sweep that retired the wrong standard, so
    doubting it again would cost a correct install its entities for no new
    reason. There is no restore cache here and none is needed."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_HOPPER_SEEN: True, _RESET_MARKER: 3},
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.options[CONF_HOPPER_SEEN] == str(Evidence.LEGACY)
    # The marker stays pinned: a downgrade reading it as absent would re-run a
    # sweep that clears a visit duration nothing can restore.
    assert mock_config_entry.options[_RESET_MARKER] == 3


async def test_a_sighting_the_old_sweeps_never_reached_is_re_examined_once(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """An install that upgraded straight past those sweeps still holds a hopper
    granted by a 0x57 link report, and a positive arrives with the hopper on a
    bench. Nothing re-proves it here, so it goes back to unproven."""
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry, options={CONF_HOPPER_SEEN: True, _RESET_MARKER: 1}
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options


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


async def test_the_recheck_accepts_native_evidence_behind_an_unavailable_state(
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

    assert bare_config_entry.options[CONF_PET_WEIGHT_SEEN] == str(Evidence.RESTORED)
    assert _disabled_by(registry, "sensor", "pet_weight") is None


async def test_a_rule_change_retires_only_what_it_disagrees_with(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The whole point of recording the evidence.

    The old global counter re-examined every sighting on every change, so
    narrowing what proves a hopper also cost installs a duration they had
    genuinely earned — and a quiet robot might not report another for a very
    long time.
    """
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={
            CONF_HOPPER_SEEN: RETIRED,
            CONF_VISIT_DURATION_SEEN: str(Evidence.VISIT_DURATION),
        },
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options
    assert bare_config_entry.options[CONF_VISIT_DURATION_SEEN] == str(Evidence.VISIT_DURATION)


async def test_evidence_from_a_newer_build_is_not_thrown_away_by_an_older_one(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A downgrade must not strip a hopper that a later, stricter standard had
    already validated: the user would then wait out another dispense to get it
    back, and this build cannot judge a kind of proof it has never heard of."""
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry, options={CONF_HOPPER_SEEN: "a_kind_from_the_future"}
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] == "a_kind_from_the_future"


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
    restore_latching_sensor(hass, bare_config_entry, "globe_motor_fault", "on")

    await setup_integration(hass, bare_config_entry, state_payload)

    assert hass.states.get(entity).state == "on"


async def test_a_restored_fault_clears_after_a_completed_clean_cycle(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """If HA was down when the clear edge fired, the latch had no way off.

    The restored answer outranks the state field by design — the field lies
    during live faults — so without an escape it re-restores itself on every
    restart, forever. The escape is positive evidence the globe turns: a fault
    DURING a cycle raises the 0x35 edge (which takes over anyway), so the
    clean-cycle odometer advancing without one means the fault is over.
    """
    entity = "binary_sensor.litter_robot_4_globe_motor_fault"
    restore_latching_sensor(hass, bare_config_entry, "globe_motor_fault", "on")
    doc = json.loads(state_payload)

    robot = await setup_integration(hass, bare_config_entry, json.dumps(doc))
    assert hass.states.get(entity).state == "on"

    # The same odometer reading again is not a completed cycle, just a heartbeat.
    with robot_online(robot):
        robot.push(json.dumps(doc))
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "on"

    doc["odometerCleanCycles"] += 1
    with robot_online(robot):
        robot.push(json.dumps(doc))
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "off"


async def test_the_first_completed_cycle_after_restore_clears_the_fault(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The baseline seeds from the startup snapshot, so the very first cycle
    to complete after a restore is the escape — not merely the calibration
    point for a second one."""
    entity = "binary_sensor.litter_robot_4_globe_motor_fault"
    restore_latching_sensor(hass, bare_config_entry, "globe_motor_fault", "on")
    doc = json.loads(state_payload)

    robot = await setup_integration(hass, bare_config_entry, json.dumps(doc))
    assert hass.states.get(entity).state == "on"

    doc["odometerCleanCycles"] += 1
    with robot_online(robot):
        robot.push(json.dumps(doc))
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "off"


async def test_a_recheck_leaves_a_user_enabled_entity_alone(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Detection records its sighting before enabling anything, so an enabled
    entity with no sighting is the user's own hand — a rule change retires
    evidence they never relied on and must not revert their choice.
    """
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

    await setup_integration(hass, bare_config_entry, state_payload)

    assert _disabled_by(registry, "sensor", "pet_weight") is None


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
        options={CONF_HOPPER_SEEN: RETIRED},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_reading",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_reading", "84"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] == str(Evidence.RESTORED)
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
        options={CONF_HOPPER_SEEN: RETIRED},
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
        options={CONF_HOPPER_FILL_RAW: 84},
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_SEEN] == str(Evidence.RESTORED)


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
        options={CONF_HOPPER_SEEN: RETIRED},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_reading",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_reading", "0"),))

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_SEEN not in bare_config_entry.options


async def test_a_restored_gauge_is_carried_at_ordinary_startup(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A hopper proven before the gauge was persisted has its reading only in
    the raw sensor's restore cache. The sweep's carry runs once per revision
    bump, so an install already at the current revision restarted into a level
    sensor reading unknown beside a raw gauge showing a real number — for days,
    until the next dispense. The carry now runs at every setup."""
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={
            **bare_config_entry.options,
            CONF_HOPPER_SEEN: str(Evidence.DISPENSE),
        },
    )
    registry = er.async_get(hass)
    for key, object_id in (
        ("hopper_fill", "litter_robot_4_hopper_reading"),
        ("hopper_level", "litter_robot_4_hopper_level"),
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{MOCK_SERIAL}_{key}",
            config_entry=bare_config_entry,
            disabled_by=None,
            suggested_object_id=object_id,
        )
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_hopper_reading", "79"),
                SensorExtraStoredData(79, None).as_dict(),
            ),
        ),
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert bare_config_entry.options[CONF_HOPPER_FILL_RAW] == 79
    state = hass.states.get("sensor.litter_robot_4_hopper_level")
    assert state is not None
    assert state.state == "54", "the provisional estimate over the typical band"
    assert state.attributes["source"] == "estimate"


async def test_an_implausible_cached_gauge_is_not_carried(
    hass: HomeAssistant, bare_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A cache written by a lone register read can hold anything, including 0;
    seeding that would anchor the level to garbage. Outside the band, nothing
    is written and the level honestly waits for a real dispense."""
    bare_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        bare_config_entry,
        options={
            **bare_config_entry.options,
            CONF_HOPPER_SEEN: str(Evidence.DISPENSE),
        },
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=bare_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_reading",
    )
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_hopper_reading", "0"),
                SensorExtraStoredData(0, None).as_dict(),
            ),
        ),
    )

    await setup_integration(hass, bare_config_entry, state_payload)

    assert CONF_HOPPER_FILL_RAW not in bare_config_entry.options
