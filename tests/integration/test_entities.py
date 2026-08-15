"""One representative entity per platform decodes from the fixture correctly."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import robot_online, setup_integration
from .const import ACTIVITY_TOPIC, MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.litter_robot_4_status", "ready"),
        ("sensor.litter_robot_4_litter_level", "62"),
        ("sensor.litter_robot_4_waste_drawer_level", "35"),
        ("binary_sensor.litter_robot_4_waste_drawer_full", "off"),
        ("binary_sensor.litter_robot_4_cat_detected", "off"),
        ("select.litter_robot_4_night_light", "auto"),
        ("number.litter_robot_4_clean_cycle_wait_time", "15"),
        ("switch.litter_robot_4_control_lock", "off"),
        ("number.litter_robot_4_night_light_brightness", "50"),
        ("time.litter_robot_4_panel_sleep_time", "22:00:00"),
    ],
)
async def test_entity_states(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    state_payload: str,
    entity_id: str,
    expected: str,
) -> None:
    await setup_integration(hass, mock_config_entry, state_payload)
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} was not created"
    assert state.state == expected


async def test_the_clean_cycle_button_sends_a_panel_press(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """The cycle is a synthesised Cycle-button press, not a macro opcode.

    The byte once shipped as "cleanCycle" (0x02A30000) turned out to reset the
    robot, so this asserts the exact wire string rather than merely that
    something was sent.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    import custom_components.whiskerless.coordinator as coord

    sent: list[str] = []
    original = coord.build_command_payload

    def spy(serial: str, code: str) -> str:
        sent.append(code)
        # The real robot echoes the button register when a press lands; that echo
        # is what the coordinator waits on before it will call the press done.
        if code == "0x02010201":
            robot.push(json.dumps({"type": "action", "data": ["0x010201"]}), ACTIVITY_TOPIC)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        with robot_online(robot):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.litter_robot_4_clean_cycle"},
                blocking=True,
            )
    finally:
        coord.build_command_payload = original

    assert "0x02010201" in sent


async def test_an_unacknowledged_press_is_never_resent(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """A press goes out exactly once, even when nothing acknowledges it.

    A lost echo does not prove the press was lost — it can land and the echo go
    missing — so resending could press twice. The user repeats it themselves,
    which is what they would do with a button that appeared not to respond.
    """
    robot = await setup_integration(hass, mock_config_entry, state_payload)

    import custom_components.whiskerless.coordinator as coord

    sent: list[str] = []
    original = coord.build_command_payload

    def spy(serial: str, code: str) -> str:  # deliberately never echoes
        sent.append(code)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        with robot_online(robot), pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.litter_robot_4_clean_cycle"},
                blocking=True,
            )
    finally:
        coord.build_command_payload = original

    assert sent.count("0x02010201") == 1, "a press must never be sent twice"


@pytest.mark.parametrize("status", [10, 13, 14])
async def test_every_cycling_status_is_representable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str, status: int
) -> None:
    """A slug the library can produce but the sensor cannot show reads unavailable.

    The status sensor is an enum, so adding a value to the decoder without adding
    it here makes the entity vanish during exactly the states it was added for.
    """
    doc = json.loads(state_payload)
    doc["robotStatus"] = status
    await setup_integration(hass, mock_config_entry, json.dumps(doc))
    state = hass.states.get("sensor.litter_robot_4_status")
    assert state is not None
    assert state.state not in ("unknown", "unavailable"), f"robotStatus {status} not representable"


async def test_the_destructive_buttons_ship_disabled(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, state_payload: str
) -> None:
    """Empty and Power must never be one stray tap away.

    Home Assistant has no entity-level confirmation prompt, so disabled-by-default
    is the only barrier the integration itself can put in front of them: an empty
    cycle costs a litter refill, and Power can leave the robot off the network
    until someone walks over to it.
    """
    await setup_integration(hass, mock_config_entry, state_payload)
    registry = er.async_get(hass)

    for key in ("start_empty_cycle", "power_toggle"):
        entity_id = registry.async_get_entity_id("button", "whiskerless", f"{MOCK_SERIAL}_{key}")
        assert entity_id is not None, f"{key} should still be registered"
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key
