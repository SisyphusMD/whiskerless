"""Activity-derived entities keep their last value across a restart."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from . import setup_integration

pytestmark = pytest.mark.usefixtures("mqtt_mock")

VISIT_AT = datetime(2026, 8, 8, 17, 40, 26, tzinfo=UTC)


async def test_a_numeric_sensor_survives_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Visit duration comes only from an activity event (reg 0xBC)."""
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_last_visit_duration", "17"),
                SensorExtraStoredData(17, UnitOfTime.SECONDS).as_dict(),
            ),
        ),
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_last_visit_duration")
    assert state is not None
    assert state.state == "17"


async def test_a_timestamp_sensor_survives_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Timestamps restore as datetimes, not re-parsed strings."""
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_last_cat_visit", VISIT_AT.isoformat()),
                SensorExtraStoredData(VISIT_AT, None).as_dict(),
            ),
        ),
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_last_cat_visit")
    assert state is not None
    assert state.state == VISIT_AT.isoformat()


async def test_a_binary_sensor_survives_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """The drawer bay register is silent until the drawer physically moves."""
    mock_restore_cache(hass, (State("binary_sensor.litter_robot_4_waste_drawer_removed", "off"),))

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("binary_sensor.litter_robot_4_waste_drawer_removed")
    assert state is not None
    assert state.state == "off"


async def test_a_fresh_install_has_nothing_to_restore(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """With no stored state the entity is honestly unknown, not a stale zero."""
    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_last_visit_duration")
    assert state is not None
    assert state.state == "unknown"


async def test_a_live_value_beats_the_restored_one(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """Restoring is a fallback, never a value that outranks the robot.

    Pet weight is the case with both sources: some firmware carries catWeight in
    the state document, and the fixture does.
    """
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_pet_weight", "4.18"),
                SensorExtraStoredData(4.18, "lb").as_dict(),
            ),
        ),
    )

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_pet_weight")
    assert state is not None
    assert state.state == "9.4"
