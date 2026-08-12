"""Activity-derived entities keep their last value across a restart."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from custom_components.whiskerless.const import CONF_HOPPER_SEEN, CONF_VISIT_DURATION_SEEN
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from . import seed_gated_sensors, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

VISIT_AT = datetime(2026, 8, 8, 17, 40, 26, tzinfo=UTC)


def _duration_reported(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Mark the robot as one that reports visit durations.

    The sensor ships disabled and enables itself on the first 0xBC, so a restore
    test needs a robot that has already produced one — which is also the only
    robot that could have written the cache these tests restore from. That means
    a registry entry already enabled: detection during *this* setup would only
    flip it after a reload, which is a different scenario from the restart these
    tests model.
    """
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_VISIT_DURATION_SEEN: True}
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_last_visit_duration",
        config_entry=entry,
        disabled_by=None,
        # Without this the pre-created entry claims a generated entity_id and the
        # platform reuses it, so the state lands somewhere these tests do not look.
        suggested_object_id="litter_robot_4_last_visit_duration",
    )


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

    _duration_reported(hass, mock_config_entry)
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
    seed_gated_sensors(hass, mock_config_entry)
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
    """The fill gauge is silent between dispenses, which can be days.

    Dispensing only happens when the litter bed is low, so a well-fed robot goes
    a long time without one and the out-of-litter alert would otherwise blank on
    every restart.
    """
    # Hopper entities ship disabled and are promoted by a reload once hardware
    # reports, so the registry entry is seeded enabled here — otherwise the
    # entity is not added during this setup and there is nothing to restore.
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, CONF_HOPPER_SEEN: True}
    )
    er.async_get(hass).async_get_or_create(
        "binary_sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_hopper_empty",
        config_entry=mock_config_entry,
        suggested_object_id="litter_robot_4_hopper_out_of_litter",
        disabled_by=None,
    )
    mock_restore_cache(hass, (State("binary_sensor.litter_robot_4_hopper_out_of_litter", "on"),))

    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("binary_sensor.litter_robot_4_hopper_out_of_litter")
    assert state is not None
    assert state.state == "on"


async def test_a_fresh_install_has_nothing_to_restore(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """With no stored state the entity is honestly unknown, not a stale zero."""
    _duration_reported(hass, mock_config_entry)
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

    Weight is carried only by the activity stream (register `0x09`), so the live
    value has to arrive as an event. No captured robot has ever put `catWeight` in
    its state document, and the raw register is hundredths of a pound, so a state
    document is not a source this sensor may fall back on.
    """
    seed_gated_sensors(hass, mock_config_entry)
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_pet_weight", "4.18"),
                SensorExtraStoredData(4.18, "lb").as_dict(),
            ),
        ),
    )

    robot = await setup_integration(hass, mock_config_entry, state_payload)
    assert hass.states.get("sensor.litter_robot_4_pet_weight").state == "4.18"

    robot.push(json.dumps({"type": "action", "data": ["0x0903AC"]}), ACTIVITY_TOPIC)  # 940 raw
    await hass.async_block_till_done()

    state = hass.states.get("sensor.litter_robot_4_pet_weight")
    assert state is not None
    assert state.state == "9.4"  # 940 / CAT_WEIGHT_DIVISOR


async def test_a_decimal_in_the_cache_is_restored_as_a_number(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """No sensor here stores a Decimal, but Home Assistant can hand one back.

    It reconstructs whatever type was serialised, and a cache written by an
    older build or another integration can hold one. Left as a Decimal it would
    reach the state machine as `Decimal('17')` instead of a number.
    """
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_last_visit_duration", "17"),
                SensorExtraStoredData(Decimal("17"), UnitOfTime.SECONDS).as_dict(),
            ),
        ),
    )

    _duration_reported(hass, mock_config_entry)
    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_last_visit_duration")
    assert state is not None
    assert float(state.state) == 17.0


async def test_a_plain_date_in_the_cache_is_refused(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
) -> None:
    """A cache holding a bare date is not one of ours, so it is not adopted.

    Every restoring sensor here is a number or a full timestamp. Taking the date
    anyway would publish a value with no time component as though the robot had
    reported it.
    """
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.litter_robot_4_last_visit_duration", "2026-08-08"),
                SensorExtraStoredData(date(2026, 8, 8), UnitOfTime.SECONDS).as_dict(),
            ),
        ),
    )

    _duration_reported(hass, mock_config_entry)
    await setup_integration(hass, mock_config_entry, state_payload)

    state = hass.states.get("sensor.litter_robot_4_last_visit_duration")
    assert state is not None
    assert state.state == "unknown"
