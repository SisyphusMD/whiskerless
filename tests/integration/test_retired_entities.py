"""Entities a previous version created but this one no longer produces."""

from __future__ import annotations

import pytest
from custom_components.whiskerless import _producible_entities
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
        f"{MOCK_SERIAL}_calibrate_litter_empty",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    assert was_disabled.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await setup_integration(hass, mock_config_entry, state_payload)

    entry = registry.async_get(was_disabled.entity_id)
    assert entry is not None
    assert entry.disabled_by is None


async def test_a_hand_disabled_entity_is_left_alone(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Someone who turned it off themselves meant it."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    chosen = registry.async_get_or_create(
        "button",
        "whiskerless",
        f"{MOCK_SERIAL}_calibrate_litter_empty",
        config_entry=mock_config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    entry = registry.async_get(chosen.entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.USER
