"""The whole entity surface, pinned.

Individual tests assert one entity at a time and so cannot notice the things that
break every dashboard at once: a renamed translation key, a device class quietly
dropped, a unit changed, an entity moved between platforms, or one that stops
being created at all. Registry entries carry the unique_id too, so this also
guards the identity that `_producible_entities` reaps against — a key that
changes shape here takes the user's entity IDs, names and areas with it.

Regenerate deliberately, never reflexively: `pytest --snapshot-update` and then
read the diff. A snapshot that changed without you meaning it is the finding.
"""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from . import setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")


async def test_the_entity_surface(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    snapshot: SnapshotAssertion,
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    entries = sorted(
        er.async_entries_for_config_entry(registry, mock_config_entry.entry_id),
        key=lambda entry: entry.entity_id,
    )
    assert entries, "the integration created no entities at all"

    for entry in entries:
        assert entry == snapshot(name=f"{entry.entity_id}-entry")
        # A disabled entity has no state, and asserting None for each of them
        # would bury the enabled ones in noise.
        if entry.disabled_by is None:
            assert hass.states.get(entry.entity_id) == snapshot(name=f"{entry.entity_id}-state")


async def test_the_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    snapshot: SnapshotAssertion,
) -> None:
    """Model, manufacturer and both firmware strings, which come from the robot."""
    await setup_integration(hass, mock_config_entry, state_payload)
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), mock_config_entry.entry_id
    )
    assert len(devices) == 1, "one robot is one device"
    assert devices[0] == snapshot


async def test_a_robot_that_stops_answering_takes_every_entity_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Availability is inherited from the coordinator, so it is all-or-nothing.

    Worth pinning separately from the snapshot: an entity that keeps publishing a
    stale value while the robot is gone is worse than one that admits it, and the
    difference is invisible in a snapshot taken while everything is healthy.
    """
    await setup_integration(hass, mock_config_entry, state_payload)
    coordinator = mock_config_entry.runtime_data

    coordinator.async_set_update_error(TimeoutError("robot went quiet"))
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    live = [
        entry.entity_id
        for entry in er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
        if entry.disabled_by is None
    ]
    assert live
    for entity_id in live:
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, entity_id
