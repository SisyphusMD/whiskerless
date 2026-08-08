"""LitterHopper entities: optional hardware, so opt-in rather than always on."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import setup_integration
from .const import MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

HOPPER_ENTITIES = (
    ("binary_sensor", "hopper_connected"),
    ("binary_sensor", "hopper_empty"),
    ("sensor", "hopper_fill"),
    ("sensor", "last_hopper_dispensed"),
)


async def test_hopper_entities_are_registered_but_disabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A hopper is optional and invisible in the state document.

    Every one of these is sourced only from hopper activity, so on a robot
    without one they would sit unknown forever. They are still registered, so
    turning them on is one click and the registry stays stable either way.
    """
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    for domain, key in HOPPER_ENTITIES:
        entity_id = registry.async_get_entity_id(domain, "whiskerless", f"{MOCK_SERIAL}_{key}")
        assert entity_id is not None, f"{key} should still be registered"
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_setup_never_re_disables_what_the_user_enabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """entity_registry_enabled_default applies at creation, not every startup.

    Pre-seed the registry entry as enabled, exactly as it would be on the run
    after someone turned it on, then set up and check nothing takes it back.
    """
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    enabled = registry.async_get_or_create(
        "binary_sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_connected",
        config_entry=mock_config_entry,
        disabled_by=None,
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    entry = registry.async_get(enabled.entity_id)
    assert entry is not None
    assert entry.disabled_by is None
    assert hass.states.get(enabled.entity_id) is not None
