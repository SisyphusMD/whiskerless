"""The EVO panel brightness blueprint, loaded by Home Assistant and run against fake levels.

The two number entities are plain states here and `number.set_value` is mocked,
so these tests pin the blueprint's own logic: which level the window asks for,
when it writes, that a level changed by hand is left alone, and that a level reset
while the robot reconnects is put back.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

BLUEPRINT = (
    Path(__file__).parents[2]
    / "blueprints"
    / "automation"
    / "whiskerless"
    / "litter_robot_evo_panel_brightness.yaml"
)
SCREEN = "number.litter_robot_evo_screen_brightness"
LED = "number.litter_robot_evo_status_led_brightness"
DISPLAY = "sensor.litter_robot_evo_display"


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return dt_util.now().replace(hour=hour, minute=minute, second=second, microsecond=0)


async def _automation(hass: HomeAssistant, tmp_path: Path, **inputs: Any) -> list[ServiceCall]:
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints" / "automation" / "whiskerless"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)
    calls = async_mock_service(hass, "number", "set_value")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"whiskerless/{BLUEPRINT.name}",
                    "input": {"screen": SCREEN, "led": LED, "display": DISPLAY, **inputs},
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


def _levels(hass: HomeAssistant, screen: str, led: str) -> None:
    hass.states.async_set(SCREEN, screen)
    hass.states.async_set(LED, led)


async def _yield(hass: HomeAssistant) -> None:
    """Let triggered runs start without waiting for a pending delay to finish."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run out the blueprint's 15-second wait after a start or a reconnect."""
    freezer.tick(timedelta(seconds=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _written(calls: list[ServiceCall]) -> list[tuple[str, int]]:
    return [(call.data["entity_id"][0] if isinstance(call.data["entity_id"], list) else call.data["entity_id"],
             int(call.data["value"])) for call in calls]


async def test_the_night_starts_with_both_levels_at_the_night_level(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(19, 59, 50))
    _levels(hass, "8", "8")
    calls = await _automation(hass, tmp_path)
    freezer.move_to(_at(20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _written(calls) == [(SCREEN, 1), (LED, 1)]


async def test_the_day_brings_back_the_day_level(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(7, 59, 50))
    _levels(hass, "1", "1")
    calls = await _automation(hass, tmp_path, day_level=20)
    freezer.move_to(_at(8))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _written(calls) == [(SCREEN, 20), (LED, 20)]


async def test_a_level_changed_by_hand_is_left_alone(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(23))
    _levels(hass, "1", "1")
    calls = await _automation(hass, tmp_path)
    _levels(hass, "20", "20")  # turned up from Home Assistant or the app
    await hass.async_block_till_done()
    await _settle(hass, freezer)
    assert calls == []


async def test_a_level_reset_while_the_robot_reconnects_is_put_back(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(23))
    _levels(hass, "1", "1")
    hass.states.async_set(DISPLAY, "idle")
    calls = await _automation(hass, tmp_path)
    for display in ("connecting", "wifi_status", "connecting", "idle"):
        hass.states.async_set(DISPLAY, display)
        await _yield(hass)
    _levels(hass, "8", "8")  # the cloud's stored preset, pushed on reconnect
    await _yield(hass)
    assert calls == []  # waits for the push and the read to land
    await _settle(hass, freezer)
    assert _written(calls) == [(SCREEN, 1), (LED, 1)]  # one write for the burst


async def test_home_assistant_start_applies_the_level_once_settled(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(23))
    _levels(hass, "8", "8")
    hass.set_state(CoreState.not_running)
    calls = await _automation(hass, tmp_path)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await _yield(hass)
    assert calls == []
    await _settle(hass, freezer)
    assert _written(calls) == [(SCREEN, 1), (LED, 1)]


async def test_a_boundary_with_both_levels_already_there_writes_nothing(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(19, 59, 50))
    _levels(hass, "1", "1")
    calls = await _automation(hass, tmp_path)
    freezer.move_to(_at(20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []


async def test_an_unreported_level_is_left_alone(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(19, 59, 50))
    _levels(hass, "unknown", "unknown")
    calls = await _automation(hass, tmp_path)
    freezer.move_to(_at(20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []


async def test_the_window_can_come_from_helpers(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    for entity_id, (hour, minute) in (
        ("input_datetime.night_start", (21, 30)),
        ("input_datetime.night_end", (6, 0)),
    ):
        hass.states.async_set(
            entity_id,
            f"{hour:02d}:{minute:02d}:00",
            {"has_date": False, "has_time": True, "hour": hour, "minute": minute, "second": 0},
        )
    freezer.move_to(_at(21, 29, 50))
    _levels(hass, "8", "8")
    calls = await _automation(
        hass,
        tmp_path,
        night_start="input_datetime.night_start",
        night_end="input_datetime.night_end",
    )
    freezer.move_to(_at(21, 30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _written(calls) == [(SCREEN, 1), (LED, 1)]


async def test_a_window_inside_one_day_works_too(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(_at(11, 59, 50))
    _levels(hass, "8", "8")
    calls = await _automation(hass, tmp_path, night_start="12:00:00", night_end="14:00:00")
    freezer.move_to(_at(12))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _written(calls) == [(SCREEN, 1), (LED, 1)]
