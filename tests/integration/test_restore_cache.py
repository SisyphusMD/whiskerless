"""The restore cache is read the same way on either side of Core 2026.11.

The harness carries one Core release, so the cache shape it does not have is
stood in for here. A reader written for one shape fails every config entry on
the other, and a suite that only ever sees one of them cannot notice.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from custom_components.whiskerless import restore
from custom_components.whiskerless.const import CONF_HOPPER_FILL_RAW, CONF_HOPPER_SEEN, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import StoredState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from whiskerless.devices.litter_robot_4.derive import Evidence

from . import setup_integration
from .const import MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

GAUGE = "sensor.litter_robot_4_hopper_reading"
LATCH = "binary_sensor.litter_robot_4_excess_weight"


def _stored(entity_id: str, state: str) -> StoredState:
    return StoredState(State(entity_id, state), None, datetime(2026, 8, 8, tzinfo=UTC))


class _KeyedByEntityId:
    """The cache before Core 2026.11: a mapping, and nothing to call."""

    def __init__(self, *stored: StoredState) -> None:
        self.last_states = {item.state.entity_id: item for item in stored}


class _KeyedByRegistryId:
    """The cache from Core 2026.11: one lookup, and no mapping to reach into."""

    def __init__(self, *stored: StoredState) -> None:
        self._stored = {item.state.entity_id: item for item in stored}

    def async_get_stored_state(self, entity_id: str) -> StoredState | None:
        return self._stored.get(entity_id)


SHAPES = pytest.mark.parametrize("shape", [_KeyedByEntityId, _KeyedByRegistryId])


def _seen_by_the_integration(cache: object) -> object:
    """Swap the cache for the integration's reads only.

    Core's own RestoreEntity keeps the real one, which is the only shape the
    Core under test can use.
    """
    return patch.object(restore, "restore_state", SimpleNamespace(async_get=lambda _hass: cache))


@SHAPES
def test_a_cached_state_is_found_on_either_core(hass: HomeAssistant, shape: type) -> None:
    with _seen_by_the_integration(shape(_stored(GAUGE, "84"))):
        found = restore.stored_state(hass, GAUGE)
        assert found is not None
        assert found.state.state == "84"
        assert restore.stored_state(hass, "sensor.never_cached") is None
        assert restore.stored_state(hass, None) is None


def test_a_rename_carries_the_state_in_a_cache_keyed_by_entity_id(hass: HomeAssistant) -> None:
    cache = _KeyedByEntityId(_stored("sensor.old_id", "84"))
    with _seen_by_the_integration(cache):
        restore.move_stored_state(hass, "sensor.old_id", "sensor.new_id")
        restore.move_stored_state(hass, "sensor.never_cached", "sensor.elsewhere")

    assert set(cache.last_states) == {"sensor.new_id"}
    assert cache.last_states["sensor.new_id"].state.state == "84"


def test_a_rename_leaves_a_cache_keyed_by_registry_id_alone(hass: HomeAssistant) -> None:
    """A registry id does not change with the entity_id, so there is nothing to
    carry, and reaching for the mapping that is no longer there must not raise."""
    cache = _KeyedByRegistryId(_stored("sensor.old_id", "84"))
    with _seen_by_the_integration(cache):
        restore.move_stored_state(hass, "sensor.old_id", "sensor.new_id")

    found = cache.async_get_stored_state("sensor.old_id")
    assert found is not None
    assert found.state.state == "84"


@SHAPES
async def test_setup_reads_what_it_cached_on_either_core(
    hass: HomeAssistant, state_payload: str, shape: type
) -> None:
    """Both setup-time readers, end to end: the sighting re-check, which runs
    before the coordinator exists, and the coordinator's restored verdict."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=MOCK_SERIAL,
        data=dict(MOCK_CONFIG),
        # Evidence the re-check no longer accepts, so the hopper survives only if
        # its cached gauge reading can be read back.
        options={CONF_HOPPER_SEEN: str(Evidence.CAT_WEIGHT)},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for domain, key, entity_id in (
        ("sensor", "hopper_fill", GAUGE),
        ("binary_sensor", "excess_weight", LATCH),
    ):
        registry.async_get_or_create(
            domain,
            DOMAIN,
            f"{MOCK_SERIAL}_{key}",
            config_entry=entry,
            disabled_by=None,
            suggested_object_id=entity_id.split(".", 1)[1],
        )
    # The scale still loaded, or the restored latch is retired by the first snapshot.
    loaded = json.dumps({**json.loads(state_payload), "catDetect": 2})

    with _seen_by_the_integration(shape(_stored(GAUGE, "84"), _stored(LATCH, "on"))):
        await setup_integration(hass, entry, loaded)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options[CONF_HOPPER_SEEN] == str(Evidence.RESTORED)
    assert entry.options[CONF_HOPPER_FILL_RAW] == 84
    latch = hass.states.get(LATCH)
    assert latch is not None
    assert latch.state == "on"


def test_the_cache_is_read_in_one_place() -> None:
    """A second reader is a second thing to break the next time Core re-keys it."""
    reaching_in = re.compile(r"restore_state\.async_get|\.last_states\b|async_get_stored_state")
    package = Path(restore.__file__).parent
    elsewhere = sorted(
        path.name
        for path in package.rglob("*.py")
        if path.name != "restore.py" and reaching_in.search(path.read_text(encoding="utf-8"))
    )
    assert elsewhere == []
