"""Integration tests for the Whiskerless Home Assistant integration.

These run under ``pytest-homeassistant-custom-component`` (Python 3.13). The root
conftest skips this directory when Home Assistant is not installed so the
standalone library tests still run.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from unittest.mock import patch

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from .const import ACTIVITY_TOPIC, MOCK_SERIAL, STATE_TOPIC

# The gated event sensors, with the object ids the platform would generate.
_GATED_SENSORS = (
    ("pet_weight", "litter_robot_4_pet_weight"),
    ("last_cat_visit", "litter_robot_4_last_cat_visit"),
    ("waste_drawer_last_moved", "litter_robot_4_waste_drawer_last_moved"),
)


def seed_gated_sensors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Pre-create the gated event sensors enabled, as on a robot whose facts
    have all reported once. The promotion path itself is covered in
    test_report_gating; state-level tests need the entities present in the
    first setup pass rather than after HA's debounced registry reload."""
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, object_id in _GATED_SENSORS:
        registry.async_get_or_create(
            "sensor",
            "whiskerless",
            f"{MOCK_SERIAL}_{key}",
            config_entry=entry,
            disabled_by=None,
            suggested_object_id=object_id,
        )


def enable_calibration_buttons(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Turn on the manual calibration buttons, as a user who wants them would.

    They ship disabled because the robot calibrates itself, so a test that
    presses one has to opt in first — which is the contract, not a workaround.
    """
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, object_id in (
        ("calibrate_litter_full", "litter_robot_4_calibrate_full"),
        ("calibrate_litter_empty", "litter_robot_4_calibrate_litter_empty"),
    ):
        registry.async_get_or_create(
            "button",
            "whiskerless",
            f"{MOCK_SERIAL}_{key}",
            config_entry=entry,
            disabled_by=None,
            suggested_object_id=object_id,
        )


def restore_latching_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, key: str, state: str
) -> None:
    """Arrange a restart for one of the latching binary sensors.

    A restart hands the integration two things: the entity registry, which
    survives, and the restore cache written from what its entities last
    reported. The coordinator reads the second through the first, so a test
    that seeds only the cache is not describing a restart that can happen.
    """
    entry.add_to_hass(hass)
    object_id = f"litter_robot_4_{key}"
    er.async_get(hass).async_get_or_create(
        "binary_sensor",
        "whiskerless",
        f"{MOCK_SERIAL}_{key}",
        config_entry=entry,
        disabled_by=None,
        suggested_object_id=object_id,
    )
    mock_restore_cache(hass, (State(f"binary_sensor.{object_id}", state),))


@dataclass
class Robot:
    """A stand-in robot that answers whatever the integration asks it.

    Tracks the LIVE subscription rather than a captured snapshot: reloading a
    config entry builds a fresh coordinator that subscribes again, and a reply
    delivered to the previous coordinator's callback reaches nobody.
    """

    payload: str
    _callback: Callable[[ReceiveMessage], None] | None = field(default=None, repr=False)

    def push(self, payload: str, topic: str = STATE_TOPIC) -> None:
        """Deliver a message as though the robot had published it."""
        assert self._callback is not None, "the integration has not subscribed yet"
        self._callback(ReceiveMessage(topic, payload, 1, False, topic, 0.0))


@contextlib.contextmanager
def robot_online(robot: Robot) -> Iterator[Robot]:
    """Answer every request the integration publishes, for as long as it is held.

    The coordinator's refresh clears its state event, publishes ``requestState``,
    then waits for a pushed state. Firing a reply blindly races that sequence and
    is wiped by the clear, which flaked on slow runners. Replying from the publish
    spy instead resolves the wait deterministically, exactly as the robot does.
    """
    real_subscribe = mqtt.async_subscribe

    async def _sub_spy(
        hass_: HomeAssistant,
        topic: str,
        msg_callback: Callable[[ReceiveMessage], None],
        **kwargs: object,
    ) -> Callable[[], None]:
        unsub = await real_subscribe(hass_, topic, msg_callback, **kwargs)
        robot._callback = msg_callback
        return unsub

    async def _pub_spy(*_args: object, **_kwargs: object) -> None:
        if robot._callback is not None:
            robot.push(robot.payload)

    with (
        patch("custom_components.whiskerless.coordinator.mqtt.async_subscribe", _sub_spy),
        patch("custom_components.whiskerless.coordinator.mqtt.async_publish", _pub_spy),
    ):
        yield robot


@contextlib.contextmanager
def capture_writes(robot: Robot, *, echo: bool = False) -> Iterator[list[str]]:
    """Record every wire code the integration publishes, newest last.

    ``echo`` also replays each accepted register write back on the activity topic.
    That is what the robot does, and what a synthesised button press waits on
    before it will call itself done — a press never reads back in the state
    document the way a settings write does.
    """
    import custom_components.whiskerless.coordinator as coord

    sent: list[str] = []
    original = coord.build_command_payload

    def spy(serial: str, code: str) -> str:
        sent.append(code)
        if echo and code.startswith("0x02") and not code.startswith("0x02A0"):
            # 0x02RRVVVV on the way out echoes back as 0xRRVVVV. The prefix is not
            # decoration: decode_activity_code rejects an element without it, so
            # dropping it produces an echo the integration discards as malformed —
            # which looks exactly like a gate working.
            activity = f"0x{code[4:]}"
            robot.push(json.dumps({"type": "action", "data": [activity]}), ACTIVITY_TOPIC)
        return original(serial, code)

    coord.build_command_payload = spy
    try:
        yield sent
    finally:
        coord.build_command_payload = original


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry, payload: str) -> Robot:
    """Set the entry up with a robot answering, and return it still armed.

    The returned Robot is NOT live once this call ends. Anything that makes the
    integration talk to the robot afterwards, including a reload triggered by
    enabling an entity, must run inside ``robot_online(robot)``.
    """
    entry.add_to_hass(hass)
    robot = Robot(payload=payload)
    with robot_online(robot):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return robot
