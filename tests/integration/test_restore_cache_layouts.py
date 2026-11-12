"""The restore cache is read the same way on both sides of Home Assistant 2026.11.

2026.11 replaced ``RestoreStateData.last_states``, one dict keyed by entity id,
with two maps (by entity id and by registry id) behind
``async_get_stored_state``. Setup read the dict directly in four places, so on
the morning that release installed every entry failed with ``AttributeError``
and every entity went unavailable while the robots kept running.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import custom_components.whiskerless as integration
import pytest
from custom_components.whiskerless import coordinator as coordinator_module
from custom_components.whiskerless.const import CONF_HOPPER_FILL_RAW, CONF_HOPPER_SEEN, DOMAIN
from custom_components.whiskerless.coordinator import stored_state
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from whiskerless.devices.litter_robot_4.derive import Evidence

from . import restore_latching_sensor, setup_integration
from .const import MOCK_CONFIG, MOCK_NAME, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

RETIRED = str(Evidence.CAT_WEIGHT)


def _stored(entity_id: str, value: str) -> restore_state.StoredState:
    return restore_state.StoredState(State(entity_id, value), None, dt_util.utcnow())


def _present(monkeypatch: pytest.MonkeyPatch, data_for: Any) -> None:
    """Hand the integration, and only the integration, a different cache object.

    Core reads the cache through the same module function, so replacing that
    would change what Home Assistant itself restores from. The integration's two
    modules each hold their own reference, and those are what get swapped.
    """
    shim = SimpleNamespace(async_get=data_for, StoredState=restore_state.StoredState)
    monkeypatch.setattr(integration, "restore_state", shim)
    monkeypatch.setattr(coordinator_module, "restore_state", shim)


class _Core2026_11:
    """The real cache, presented the way 2026.11 presents it: no ``last_states``."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def async_get_stored_state(self, entity_id: str) -> restore_state.StoredState | None:
        return self._real.last_states.get(entity_id)


@pytest.fixture
def core_2026_11(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the integration against the 2026.11 cache layout.

    On a core that already has it there is nothing to stand in for, so the real
    object is passed through untouched.
    """
    real_get = restore_state.async_get

    def data_for(hass: HomeAssistant) -> Any:
        real = real_get(hass)
        return _Core2026_11(real) if hasattr(real, "last_states") else real

    _present(monkeypatch, data_for)
    yield


def test_the_lookup_goes_through_the_accessor_when_core_has_one(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026.11 and later: the dict is gone, so nothing may reach for it."""
    stored = _stored("sensor.litter_robot_4_hopper_reading", "84")
    asked: list[str] = []

    class Core:
        def async_get_stored_state(self, entity_id: str) -> restore_state.StoredState | None:
            asked.append(entity_id)
            return stored

    _present(monkeypatch, lambda hass: Core())

    assert stored_state(hass, "sensor.litter_robot_4_hopper_reading") is stored
    assert asked == ["sensor.litter_robot_4_hopper_reading"]


def test_the_lookup_falls_back_to_the_dict_on_an_older_core(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before 2026.11 there is no accessor, and the dict is the only way in."""
    stored = _stored("sensor.litter_robot_4_hopper_reading", "84")
    older = SimpleNamespace(last_states={"sensor.litter_robot_4_hopper_reading": stored})
    _present(monkeypatch, lambda hass: older)

    assert stored_state(hass, "sensor.litter_robot_4_hopper_reading") is stored
    assert stored_state(hass, "sensor.litter_robot_4_never_stored") is None


@pytest.mark.usefixtures("core_2026_11")
async def test_a_restored_fill_gauge_still_proves_a_hopper_on_2026_11(
    hass: HomeAssistant, state_payload: str
) -> None:
    """The hopper seed and the sighting re-check both read the cache at setup.

    These are the two reads that took setup down: the first raised before the
    coordinator existed, so nothing after it ever ran.
    """
    entry = MockConfigEntry(
        domain=DOMAIN, title=MOCK_NAME, unique_id=MOCK_SERIAL, data=dict(MOCK_CONFIG)
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_HOPPER_SEEN: RETIRED})
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_reading",
    )
    mock_restore_cache(hass, (State("sensor.litter_robot_4_hopper_reading", "84"),))

    await setup_integration(hass, entry, state_payload)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options[CONF_HOPPER_SEEN] == str(Evidence.RESTORED)
    assert entry.options[CONF_HOPPER_FILL_RAW] == 84


@pytest.mark.usefixtures("core_2026_11")
async def test_a_latched_sensor_still_restores_on_2026_11(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The coordinator seeds its latching sensors from the same cache."""
    loaded = json.dumps({**json.loads(state_payload), "catDetect": 2})
    restore_latching_sensor(hass, mock_config_entry, "excess_weight", "on")

    await setup_integration(hass, mock_config_entry, loaded)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.litter_robot_4_excess_weight").state == "on"


@pytest.mark.usefixtures("core_2026_11")
async def test_an_entity_rename_does_not_reach_for_the_old_dict_on_2026_11(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """2026.11 keys the cache by registry id, so a rename needs no help there.

    The rename used to move the entry inside the dict by hand. With the dict
    gone that step must be skipped, not attempted.
    """
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_HOPPER_SEEN: str(Evidence.DISPENSE)},
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MOCK_SERIAL}_hopper_fill",
        config_entry=mock_config_entry,
        disabled_by=None,
        suggested_object_id="litter_robot_4_hopper_fill_raw",
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert registry.async_get("sensor.litter_robot_4_hopper_reading") is not None
    assert registry.async_get("sensor.litter_robot_4_hopper_fill_raw") is None
