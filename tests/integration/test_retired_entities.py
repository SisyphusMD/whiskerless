"""Entities a previous version created but this one no longer produces."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from custom_components.whiskerless import _producible_entities
from custom_components.whiskerless.const import CONF_HOPPER_SEEN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from whiskerless.devices.litter_robot_4.derive import Evidence

from . import setup_integration
from .const import MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")


async def test_retired_entity_is_removed_on_upgrade(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A withdrawn capability must not linger as a permanently dead entity."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    retired = registry.async_get_or_create(
        "select",
        "whiskerless",
        f"{MOCK_SERIAL}_clean_cycle_wait",
        config_entry=mock_config_entry,
    )
    assert registry.async_get(retired.entity_id) is not None

    await setup_integration(hass, mock_config_entry, state_payload)

    assert registry.async_get(retired.entity_id) is None


async def test_moving_an_entity_between_domains_drops_the_old_one(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Registry identity includes the domain, so a moved entity leaves an orphan.

    The clean-cycle wait moved from a preset select to a number over the range
    the firmware actually accepts; the select entry cannot be adopted.
    """
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "select",
        "whiskerless",
        f"{MOCK_SERIAL}_clean_cycle_wait",
        config_entry=mock_config_entry,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert registry.async_get(old.entity_id) is None
    assert hass.states.get("number.litter_robot_4_clean_cycle_wait_time") is not None


async def test_every_created_entity_is_declared_producible(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Guards the sweep against drift.

    An entity the platforms create but the producible set omits would be deleted
    and recreated on every reload, silently discarding the user's entity ID,
    name, area and enabled state.
    """
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    producible = _producible_entities(MOCK_SERIAL)
    created = {
        (e.domain, e.unique_id)
        for e in er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    }
    assert created <= producible, f"created but not declared: {sorted(created - producible)}"


async def test_a_downgrade_does_not_reap_the_newer_version_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """To an older build, everything a newer one added looks retired."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"retired_entities_swept_by": "99.0.0"}
    )
    registry = er.async_get(hass)
    from_the_future = registry.async_get_or_create(
        "sensor", "whiskerless", f"{MOCK_SERIAL}_not_invented_yet", config_entry=mock_config_entry
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert registry.async_get(from_the_future.entity_id) is not None


async def test_skipping_versions_still_sweeps(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The gate is a version comparison, not a chain of migrations.

    Jumping several releases in one go must still clean up everything retired
    along the way, because the producible set is declarative rather than a
    sequence of per-version steps that all have to be visited.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"retired_entities_swept_by": "0.0.1"}
    )
    registry = er.async_get(hass)
    retired = registry.async_get_or_create(
        "select", "whiskerless", f"{MOCK_SERIAL}_clean_cycle_wait", config_entry=mock_config_entry
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert registry.async_get(retired.entity_id) is None


async def test_live_entities_survive_the_sweep(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The sweep must only take entities this version cannot produce."""
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    entries = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    assert entries, "the sweep removed everything"
    # Activity-derived entities have no value until the robot reports one, which
    # is exactly the shape that a naive 'created this run' sweep would delete.
    assert registry.async_get_entity_id("sensor", "whiskerless", f"{MOCK_SERIAL}_pet_weight")
    assert registry.async_get_entity_id(
        "binary_sensor", "whiskerless", f"{MOCK_SERIAL}_hopper_connected"
    )


async def test_an_entity_that_became_default_on_is_enabled_on_upgrade(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Flipping the platform default does nothing for entities that already exist.

    A registry entry keeps the disabled_by it was created with, so without an
    explicit promotion the change is invisible to every existing install — which
    is everyone who would benefit from it.
    """
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    was_disabled = registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_refresh",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    assert was_disabled.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await setup_integration(hass, mock_config_entry, state_payload)

    entry = registry.async_get(was_disabled.entity_id)
    assert entry is not None
    assert entry.disabled_by is None


async def test_an_existing_install_gets_the_wifi_signal_it_was_never_shown(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The sensor shipped disabled, so the field that explains a dropout was invisible
    exactly on the installs that had been dropping out. Flipping the default only
    reaches new registrations; existing entries need the explicit promotion."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_wifi_rssi",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    entity_id = registry.async_get_entity_id("sensor", "whiskerless", f"{MOCK_SERIAL}_wifi_rssi")
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is None


async def test_a_hand_disabled_wifi_signal_stays_off(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Promotion must not override a person who turned this one off deliberately."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_wifi_rssi",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    entity_id = registry.async_get_entity_id("sensor", "whiskerless", f"{MOCK_SERIAL}_wifi_rssi")
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.USER


async def test_a_hand_disabled_entity_is_left_alone(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Someone who turned it off themselves meant it."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_calibrate_litter_empty",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    # By unique_id, not the id captured above: 0.2.0 renames this button, and the
    # question here is whether the USER's disable survived, not where it lives.
    entity_id = registry.async_get_entity_id(
        "button", "whiskerless", f"{MOCK_SERIAL}_calibrate_litter_empty"
    )
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.USER


async def test_the_mm_sensors_are_moved_to_millimetres_on_upgrade(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """An install that predates the pin is showing inches, and would keep doing so.

    `suggested_unit_of_measurement` only seeds an entity at FIRST registration —
    core deliberately pins an existing entity to the unit it already had, so that
    adding a suggestion never moves the ground under a user. Reaching the people
    who already have the integration takes an explicit refresh.
    """
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    existing = registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_litter_reference",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_litter_calibration_reference",
    )
    # What an imperial install looks like before the pin: core stored ITS
    # suggestion (inches), and the user has expressed no preference.
    registry.async_update_entity_options(
        existing.entity_id, "sensor.private", {"suggested_unit_of_measurement": "in"}
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    # Resolved after setup: this sensor is one of the ones 0.2.0 renames.
    entity_id = registry.async_get_entity_id(
        "sensor", "whiskerless", f"{MOCK_SERIAL}_litter_reference"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["unit_of_measurement"] == "mm"


async def test_a_unit_the_user_picked_is_left_alone(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A unit in the plain `sensor` options is the user's own override — core
    says so explicitly — so the pin must not overwrite it with a preference of
    ours dressed up as theirs."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    existing = registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_litter_reference",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_litter_calibration_reference",
    )
    registry.async_update_entity_options(
        existing.entity_id, "sensor", {"unit_of_measurement": "in"}
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    # Resolved after setup: this sensor is one of the ones 0.2.0 renames.
    entity_id = registry.async_get_entity_id(
        "sensor", "whiskerless", f"{MOCK_SERIAL}_litter_reference"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["unit_of_measurement"] == "in"


async def test_an_entity_keeps_its_name_across_installs(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A display-name change only reaches NEW entities, so without this an install
    from last month and one from today answer to different ids for the same button."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    existing = registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_start_clean_cycle",
    )
    assert existing.entity_id == "button.litter_robot_4_start_clean_cycle"

    await setup_integration(hass, mock_config_entry, state_payload)

    moved = registry.async_get_entity_id("button", "whiskerless", f"{MOCK_SERIAL}_start_clean_cycle")
    assert moved == "button.litter_robot_4_clean_cycle"


async def test_an_id_the_user_chose_is_never_moved(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Renaming an entity is how someone says what they want it called, and that
    outranks our tidiness — every automation they wrote uses their name."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    chosen = registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="scoop_the_box",
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert registry.async_get(chosen.entity_id) is not None


async def test_a_rename_never_lands_on_an_id_already_in_use(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Taking an occupied id would be worse than leaving the old one in place."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_start_clean_cycle",
    )
    squatter = registry.async_get_or_create(
        "button", "other_integration", "squatter", suggested_object_id="litter_robot_4_clean_cycle"
    )
    assert squatter.entity_id == "button.litter_robot_4_clean_cycle"

    await setup_integration(hass, mock_config_entry, state_payload)

    assert (
        registry.async_get_entity_id("button", "whiskerless", f"{MOCK_SERIAL}_start_clean_cycle")
        == "button.litter_robot_4_start_clean_cycle"
    )


async def test_a_disambiguated_id_is_renamed_with_its_counter(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Core appends _2 when a second device shares a name. That id is just as
    generated as the plain one, and skipping it would strand the second robot."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_start_clean_cycle_2",
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert (
        registry.async_get_entity_id("button", "whiskerless", f"{MOCK_SERIAL}_start_clean_cycle")
        == "button.litter_robot_4_clean_cycle_2"
    )


async def test_a_rename_blocked_by_a_live_entity_does_not_break_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """An entity with no unique_id has a state but no registry row, and core
    refuses the id with a ValueError that would abort the whole integration."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_start_clean_cycle",
    )
    hass.states.async_set("button.litter_robot_4_clean_cycle", "unknown")

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert (
        registry.async_get_entity_id("button", "whiskerless", f"{MOCK_SERIAL}_start_clean_cycle")
        == "button.litter_robot_4_start_clean_cycle"
    )


async def test_a_rename_that_fails_anyway_never_takes_setup_down(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The checks above should make this unreachable, and it stays here anyway:
    losing every entity on this robot because a cosmetic rename raised is a far
    worse trade than an entity keeping its old name."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_start_clean_cycle",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_start_clean_cycle",
    )

    real = er.EntityRegistry.async_update_entity

    def only_renames_fail(self: object, entity_id: str, **kwargs: object) -> object:
        if "new_entity_id" in kwargs:
            raise ValueError("taken")
        return real(self, entity_id, **kwargs)  # type: ignore[arg-type]

    with patch.object(er.EntityRegistry, "async_update_entity", only_renames_fail):
        await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_a_renamed_entity_keeps_what_it_had_restored(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The restore cache is keyed by entity_id. Without carrying it across, the
    hopper gauge comes back unknown — and that reading is what the detection
    sweep accepts as proof the hardware exists."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_fill_raw",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_fill_raw", "84"),))

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_hopper_reading")
    assert state is not None
    assert state.state == "84"
