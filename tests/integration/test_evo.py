"""The Litter-Robot EVO in Home Assistant: discovery, entities, telemetry and writes.

The EVO has no state document, so every entity starts unknown and fills in from
what the robot publishes. A write is verified by the robot's echo of it, so the
stand-in robot here echoes every command it receives, the way the robot does.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import custom_components.whiskerless.evo.coordinator as evo_coordinator_module
import pytest
from custom_components.whiskerless.const import CONF_MODEL, DOMAIN, MODEL_EVO, SIGNAL_EVO_EVENT
from custom_components.whiskerless.diagnostics import async_get_config_entry_diagnostics
from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import SOURCE_MQTT, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from syrupy.assertion import SnapshotAssertion

from whiskerless.devices.litter_robot_evo import PawprintMessage
from whiskerless.devices.litter_robot_evo import commands as evo_commands
from whiskerless.devices.litter_robot_evo import const as evo_const

from .const import (
    EVO_ACTIVITY_TOPIC,
    EVO_COMMAND_TOPIC,
    EVO_EVENT_TOPIC,
    EVO_NAME,
    EVO_SERIAL,
    MOCK_CONFIG,
)

pytestmark = pytest.mark.usefixtures("mqtt_mock")


@dataclass
class EvoRobot:
    """A stand-in EVO that echoes every write it receives."""

    callback: Callable[[ReceiveMessage], None] | None = field(default=None, repr=False)
    sent: list[list[str]] = field(default_factory=list)
    echo: bool = True
    #: Wire code -> the elements the robot answers it with, where that differs
    #: from a plain echo (an action reports the resulting status).
    replies: dict[str, list[str]] = field(default_factory=dict)
    #: "BBRR" -> value: what a read of that register answers. Reads of anything
    #: else get no element, and a message of reads with none known gets no reply.
    registers: dict[str, int] = field(default_factory=dict)
    #: What the integration sent while it was set up (before `sent` was cleared).
    setup_sent: list[list[str]] = field(default_factory=list)
    #: Clock writes, kept apart from `sent` so other tests see only their own traffic.
    clock_sent: list[list[str]] = field(default_factory=list)
    #: Make a clock write fail to publish.
    fail_clock: bool = False

    def push(
        self, data: list[Any], *, topic: str = EVO_ACTIVITY_TOPIC, kind: str = "activity", **extra: Any
    ) -> None:
        """Deliver a message as though the robot had published it."""
        assert self.callback is not None, "the integration has not subscribed yet"
        payload = json.dumps({"type": kind, "data": data, **extra})
        self.callback(ReceiveMessage(topic, payload, 1, False, topic, 0.0))

    def push_raw(self, payload: str, topic: str = EVO_ACTIVITY_TOPIC) -> None:
        assert self.callback is not None
        self.callback(ReceiveMessage(topic, payload, 1, False, topic, 0.0))


@contextlib.contextmanager
def evo_online(robot: EvoRobot) -> Iterator[EvoRobot]:
    """Track the live subscription and answer every publish with its echo."""
    real_subscribe = mqtt.async_subscribe

    async def _subscribe(
        hass_: HomeAssistant, topic: str, msg_callback: Callable[[ReceiveMessage], None], **kwargs: Any
    ) -> Callable[[], None]:
        unsub = await real_subscribe(hass_, topic, msg_callback, **kwargs)
        robot.callback = msg_callback
        return unsub

    async def _publish(_hass: HomeAssistant, topic: str, payload: str, *_args: Any, **_kwargs: Any) -> None:
        assert topic == EVO_COMMAND_TOPIC
        body = json.loads(payload)
        assert body["serial"] == EVO_SERIAL
        if [code[4:8] for code in body["data"]] == [f"02{r:02X}" for r in evo_const.CLOCK_REGS]:
            if robot.fail_clock:
                raise HomeAssistantError("broker unavailable")
            robot.clock_sent.append(body["data"])
        else:
            robot.sent.append(body["data"])
        if all(code.startswith("0x01") for code in body["data"]):
            answers = [
                f"0x{code[4:8]}{robot.registers[code[4:8]]:04X}"
                for code in body["data"]
                if code[4:8] in robot.registers
            ]
            if answers:
                robot.push(answers, kind="query")
            return
        if robot.echo:
            reply: list[str] = []
            for code in body["data"]:
                reply += robot.replies.get(code, [f"0x{code[4:]}"])
            robot.push(reply)

    with (
        patch.object(evo_coordinator_module.mqtt, "async_subscribe", _subscribe),
        patch.object(evo_coordinator_module.mqtt, "async_publish", _publish),
    ):
        yield robot


async def _advance(hass: HomeAssistant, seconds: float) -> None:
    """Fire every timer due within ``seconds`` from now and let the work finish."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


#: Past the setup read's delay.
_AFTER_SETUP_READ = 6
#: Past a read's reply timeout.
_AFTER_READ_TIMEOUT = 11


@pytest.fixture
async def evo(hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry) -> AsyncIterator[EvoRobot]:
    """An EVO entry set up and its setup read answered.

    The robot answers a read of bank 01 register 06, which no entity shows, so the
    setup read seeds state without filling in any entity.
    """
    robot = EvoRobot(registers={"0106": 0x04})
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        robot.setup_sent = list(robot.sent)
        robot.sent.clear()
        yield robot


def _eid(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{EVO_SERIAL}_{key}")
    assert entity_id is not None, f"{platform} {key} was not created"
    return entity_id


def _state(hass: HomeAssistant, platform: str, key: str) -> str:
    state = hass.states.get(_eid(hass, platform, key))
    assert state is not None
    return state.state


async def _call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


# --- discovery ----------------------------------------------------------------
def _discovery(topic: str) -> MqttServiceInfo:
    return MqttServiceInfo(
        topic=topic, payload="{}", qos=1, retain=False, subscribed_topic=topic, timestamp=0.0
    )


async def test_an_evo_is_discovered_on_its_own_topics(hass: HomeAssistant, mock_setup_entry: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery(EVO_ACTIVITY_TOPIC)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"serial": EVO_SERIAL, "model": EVO_NAME}
    flow = hass.config_entries.flow.async_get(result["flow_id"])
    assert flow["context"]["title_placeholders"] == {"name": f"{EVO_NAME} ({EVO_SERIAL})"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "  "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EVO_NAME
    assert result["data"] == {"serial": EVO_SERIAL, "name": EVO_NAME, CONF_MODEL: MODEL_EVO}


async def test_a_litter_robot_4_entry_still_carries_no_model(hass: HomeAssistant, mock_setup_entry: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery("prod/LR4/LR4C000001/state")
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Box"})
    assert result["data"] == {"serial": "LR4C000001", "name": "Box"}


async def test_only_a_litter_robot_4_has_an_options_page(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    mock_evo_config_entry.add_to_hass(hass)
    lr4 = MockConfigEntry(domain=DOMAIN, unique_id="LR4C000001", data=dict(MOCK_CONFIG))
    lr4.add_to_hass(hass)
    assert not mock_evo_config_entry.supports_options
    assert lr4.supports_options


# --- setup --------------------------------------------------------------------
async def test_the_evo_entity_surface(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry, snapshot: SnapshotAssertion
) -> None:
    registry = er.async_get(hass)
    entries = sorted(
        er.async_entries_for_config_entry(registry, mock_evo_config_entry.entry_id),
        key=lambda entry: entry.entity_id,
    )
    assert entries
    for entry in entries:
        assert entry == snapshot(name=f"{entry.entity_id}-entry")
        if entry.disabled_by is None:
            assert hass.states.get(entry.entity_id) == snapshot(name=f"{entry.entity_id}-state")
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_evo_config_entry.entry_id)
    assert len(devices) == 1
    assert devices[0] == snapshot(name="device")


_READ_ALL = [command.code for command in evo_commands.read_all()]


async def test_setup_reads_every_readable_register_in_one_message(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    robot = EvoRobot(
        registers={"0103": 0x04, "0114": 1, "0120": 0, "0201": 0x0808, "0209": 7, "020A": 0, "0105": 9}
    )
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        assert robot.sent == []  # waits for the subscription to reach the broker
        await _advance(hass, _AFTER_SETUP_READ)
        assert robot.sent == [_READ_ALL]
        assert _state(hass, "sensor", "robot_status") == "ready"
        assert _state(hass, "number", "screen_brightness") == "8"
        assert _state(hass, "switch", "keypad_lockout") == STATE_OFF
        assert _state(hass, "binary_sensor", "drawer_removed") == STATE_OFF
        assert _state(hass, "sensor", "panel_display") == STATE_UNKNOWN  # cannot be read


async def test_everything_stays_unknown_while_the_reads_go_unanswered(
    hass: HomeAssistant, evo: EvoRobot
) -> None:
    for platform, key in (
        ("number", "screen_brightness"),
        ("select", "panel_brightness_preset"),
        ("switch", "keypad_lockout"),
        ("time", "panel_sleep_time"),
        ("sensor", "robot_status"),
        ("binary_sensor", "drawer_removed"),
    ):
        assert _state(hass, platform, key) == STATE_UNKNOWN
    assert evo.setup_sent == [_READ_ALL]


async def test_a_reconnect_reads_the_registers_again_once(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.registers = {"0209": 15}
    evo.push(["0x01020066"])
    evo.push(["0x01020026"])
    evo.push(["0x01020067"])
    await hass.async_block_till_done()
    assert evo.sent == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert evo.sent == [_READ_ALL]
    assert _state(hass, "select", "cycle_delay") == "15"


async def test_an_answered_read_sets_the_robot_clock_once(hass: HomeAssistant, evo: EvoRobot) -> None:
    (clock,) = evo.clock_sent
    now = dt_util.now()
    assert [code[6:8] for code in clock] == [f"{r:02X}" for r in evo_const.CLOCK_REGS]
    assert clock[-1] == f"0x020208{now.year % 100:04X}"
    assert clock[0] == f"0x020202{(now.weekday() + 1) % 7:04X}"


async def test_a_reconnect_sets_the_clock_again_once(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x01020066"])
    evo.push(["0x01020067"])
    await _advance(hass, 5)
    assert len(evo.clock_sent) == 2


async def test_no_clock_write_while_the_reads_go_unanswered(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    robot = EvoRobot()
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        for _ in range(3):
            await _advance(hass, _AFTER_READ_TIMEOUT)
        assert robot.clock_sent == []


async def test_a_failed_clock_write_is_logged(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    robot = EvoRobot(registers={"0106": 0x04}, fail_clock=True)
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        assert robot.clock_sent == []
        assert "Could not set the clock" in caplog.text
        assert mock_evo_config_entry.state is ConfigEntryState.LOADED


async def test_a_read_reply_of_zero_for_the_display_never_hides_telemetry(
    hass: HomeAssistant, evo: EvoRobot
) -> None:
    evo.push(["0x01020016"])
    evo.push(["0x01020000", "0x02090007"], kind="query")
    await hass.async_block_till_done()
    assert _state(hass, "sensor", "panel_display") == "idle"
    assert _state(hass, "select", "cycle_delay") == "7"


async def test_a_failed_read_is_logged_and_setup_still_succeeds(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    async def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise HomeAssistantError("not connected")

    robot = EvoRobot()
    with evo_online(robot), patch.object(evo_coordinator_module.mqtt, "async_publish", _fail):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        for _ in range(3):
            await _advance(hass, _AFTER_READ_TIMEOUT)
    assert mock_evo_config_entry.state is ConfigEntryState.LOADED
    assert "Could not read the state" in caplog.text


async def test_an_unanswered_read_is_repeated_and_the_repeat_fills_the_entities(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    robot = EvoRobot()
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        assert robot.sent == [_READ_ALL]
        assert _state(hass, "select", "cycle_delay") == STATE_UNKNOWN
        robot.registers = {"0209": 7}
        await _advance(hass, _AFTER_READ_TIMEOUT)
        assert robot.sent == [_READ_ALL, _READ_ALL]
        assert _state(hass, "select", "cycle_delay") == "7"
        await _advance(hass, _AFTER_READ_TIMEOUT)
        assert robot.sent == [_READ_ALL, _READ_ALL]  # answered: no more retries


async def test_unanswered_reads_stop_after_three(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    robot = EvoRobot()
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        for _ in range(4):
            await _advance(hass, _AFTER_READ_TIMEOUT)
        assert robot.sent == [_READ_ALL] * 3
        assert caplog.text.count("did not answer 3 reads") == 1


async def test_a_message_while_no_read_is_answered_starts_one_read(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    robot = EvoRobot()
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        for _ in range(3):
            await _advance(hass, _AFTER_READ_TIMEOUT)
        robot.sent.clear()
        robot.registers = {"0103": 0x04}
        robot.push(["0x01020016"])
        robot.push(["0x01200001"])
        robot.push(["0x01200000"])
        await hass.async_block_till_done()
        assert robot.sent == []
        await _advance(hass, 4)
        assert robot.sent == [_READ_ALL]
        assert _state(hass, "sensor", "robot_status") == "ready"
        robot.push(["0x01020016"])  # answered now: no further read
        await _advance(hass, 4)
        assert robot.sent == [_READ_ALL]


async def test_an_unload_cancels_a_pending_retry(
    hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry
) -> None:
    robot = EvoRobot()
    with evo_online(robot):
        mock_evo_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
        await _advance(hass, _AFTER_SETUP_READ)
        assert robot.sent == [_READ_ALL]
        assert await hass.config_entries.async_unload(mock_evo_config_entry.entry_id)
        await _advance(hass, _AFTER_READ_TIMEOUT)
        assert robot.sent == [_READ_ALL]


async def test_an_unload_cancels_a_pending_read(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry
) -> None:
    evo.push(["0x01020066"])
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_evo_config_entry.entry_id)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert evo.sent == []


async def test_setup_waits_for_mqtt(hass: HomeAssistant, mock_evo_config_entry: MockConfigEntry) -> None:
    mock_evo_config_entry.add_to_hass(hass)
    with patch.object(evo_coordinator_module.mqtt, "async_wait_for_mqtt_client", return_value=False):
        await hass.config_entries.async_setup(mock_evo_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_evo_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_an_evo_entry_unloads(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_unload(mock_evo_config_entry.entry_id)
    assert mock_evo_config_entry.state is ConfigEntryState.NOT_LOADED


# --- telemetry ----------------------------------------------------------------
async def test_telemetry_fills_in_the_entities(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(
        [
            "0x02010808",  # panel brightness, screen 8 / LED 8
            "0x02090007",  # cycle delay 7
            "0x020A0001",  # lockout on
            "0x02100041",  # sleep on Sunday and Saturday
            *[f"0x02{0x11 + i:02X}{(0 if i % 2 == 0 else 720):04X}" for i in range(14)],
            "0x01030004",  # ready
            "0x01020016",  # idle
            "0x01140001",  # powered on
            "0x01180000",  # bonnet on
            "0x01200001",  # drawer out
            "0x051BFFD6",  # weight, raw -42
            "0x050A000F",  # drawer counter
            "0x010A0003",  # cycle step
            "0x01050009",  # power-cycle odometer
            "0x01070002",  # empty-cycle odometer
        ]
    )
    await hass.async_block_till_done()
    assert _state(hass, "number", "screen_brightness") == "8"
    assert _state(hass, "number", "status_led_brightness") == "8"
    assert _state(hass, "select", "panel_brightness_preset") == "low"
    assert _state(hass, "select", "cycle_delay") == "7"
    assert _state(hass, "switch", "keypad_lockout") == "on"
    assert _state(hass, "switch", "weekday_sleep") == "on"
    assert _state(hass, "time", "panel_sleep_time") == "00:00:00"
    assert _state(hass, "time", "panel_wake_time") == "12:00:00"
    assert _state(hass, "sensor", "robot_status") == "ready"
    assert _state(hass, "sensor", "panel_display") == "idle"
    assert _state(hass, "binary_sensor", "power") == "on"
    assert _state(hass, "binary_sensor", "bonnet_removed") == "off"
    assert _state(hass, "binary_sensor", "drawer_removed") == "on"
    assert _state(hass, "binary_sensor", "cleaning") == "off"
    assert _state(hass, "sensor", "power_cycle_count") == "9"
    assert _state(hass, "sensor", "empty_cycle_count") == "2"


async def test_a_custom_pair_has_no_preset(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x02010801"])
    await hass.async_block_till_done()
    assert _state(hass, "select", "panel_brightness_preset") == STATE_UNKNOWN
    assert _state(hass, "number", "status_led_brightness") == "1"


async def test_an_unlisted_cycle_delay_reads_as_unknown(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x02090004", "0x02100000"])
    await hass.async_block_till_done()
    assert _state(hass, "select", "cycle_delay") == STATE_UNKNOWN
    assert _state(hass, "switch", "weekday_sleep") == "off"


async def test_unreadable_read_replies_and_junk_change_nothing(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x01020000"], kind="query")  # the display code answers reads with 0
    evo.push_raw("not json")
    evo.push_raw(json.dumps({"serial": EVO_SERIAL, "data": ["0x0202010808"]}), EVO_COMMAND_TOPIC)
    await hass.async_block_till_done()
    assert _state(hass, "sensor", "panel_display") == STATE_UNKNOWN
    assert _state(hass, "number", "screen_brightness") == STATE_UNKNOWN


async def test_a_failing_message_does_not_break_the_subscription(
    hass: HomeAssistant, evo: EvoRobot, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(evo_coordinator_module, "apply_message", side_effect=RuntimeError("boom")):
        evo.push(["0x02010808"])
    assert "Error handling MQTT message" in caplog.text
    evo.push(["0x02010808"])
    await hass.async_block_till_done()
    assert _state(hass, "number", "screen_brightness") == "8"


async def test_messages_during_unload_are_ignored(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry
) -> None:
    mock_evo_config_entry.mock_state(hass, ConfigEntryState.UNLOAD_IN_PROGRESS)
    evo.push(["0x02010808"])
    assert mock_evo_config_entry.runtime_data.data.screen_brightness is None


async def test_cycle_and_usage_records_fire_the_event(hass: HomeAssistant, evo: EvoRobot) -> None:
    entity_id = _eid(hass, "event", "robot_event")
    evo.push(["0x01030004", "0x050A000F"], topic=EVO_EVENT_TOPIC, kind="cycle", uuid="u-1")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["event_type"] == "cycle"
    assert state.attributes["uuid"] == "u-1"
    assert state.attributes["data"] == ["0x01030004", "0x050A000F"]

    evo.push(["0x03050004"], topic=EVO_EVENT_TOPIC, kind="mystery")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["event_type"] == "cycle", "an unknown record type does not fire"


async def test_a_usage_record_carries_the_weight(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x01030004", "0x03050030", "0x03060373"], topic=EVO_EVENT_TOPIC, kind="usage", uuid="u-2")
    await hass.async_block_till_done()
    state = hass.states.get(_eid(hass, "event", "robot_event"))
    assert state is not None
    assert state.attributes["event_type"] == "usage"
    assert state.attributes["weight_lb"] == 8.83
    assert _state(hass, "sensor", "pet_weight") == "8.83"


async def test_a_pet_match_fires_the_event(hass: HomeAssistant, evo: EvoRobot) -> None:
    """The profile id is invented."""
    entity_id = _eid(hass, "event", "robot_event")
    match = {"type": "pet_id_match", "profile": "PET-00000000-0000-0000-0000-000000000000",
             "confidence": 0.97, "sources": ["weight"]}
    evo.push([match], kind="pawprint")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["event_type"] == "pet_id_match"
    assert state.attributes["profile"] == "PET-00000000-0000-0000-0000-000000000000"
    assert state.attributes["confidence"] == 0.97
    assert state.attributes["sources"] == ["weight"]

    evo.push([{"type": "pet_profile_request"}], kind="pawprint")
    await hass.async_block_till_done()
    after = hass.states.get(entity_id)
    assert after is not None
    assert after.last_changed == state.last_changed, "other pawprint messages do not fire"

    async_dispatcher_send(
        hass, SIGNAL_EVO_EVENT.format(EVO_SERIAL), PawprintMessage(message_type="pet_profile_request")
    )
    await hass.async_block_till_done()
    dispatched = hass.states.get(entity_id)
    assert dispatched is not None
    assert dispatched.last_changed == state.last_changed


# --- writes -------------------------------------------------------------------
async def test_the_panel_preset_sets_both_levels(hass: HomeAssistant, evo: EvoRobot) -> None:
    await _call(hass, "select", "select_option", _eid(hass, "select", "panel_brightness_preset"), option="high")
    assert evo.sent[-1] == ["0x0202012828"]
    assert _state(hass, "number", "screen_brightness") == "40"


async def test_off_sets_both_levels_to_one(hass: HomeAssistant, evo: EvoRobot) -> None:
    preset = _eid(hass, "select", "panel_brightness_preset")
    await _call(hass, "select", "select_option", preset, option="off")
    assert evo.sent[-1] == ["0x0202010101"]
    assert _state(hass, "select", "panel_brightness_preset") == "off"
    evo.push(["0x02010808"])
    await hass.async_block_till_done()
    assert _state(hass, "select", "panel_brightness_preset") == "low"
    evo.push(["0x02010101"])
    await hass.async_block_till_done()
    assert _state(hass, "select", "panel_brightness_preset") == "off"


async def test_each_level_moves_on_its_own(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.push(["0x02010808"])
    await hass.async_block_till_done()
    await _call(hass, "number", "set_value", _eid(hass, "number", "status_led_brightness"), value=1)
    assert evo.sent[-1] == ["0x0202010801"]
    await _call(hass, "number", "set_value", _eid(hass, "number", "screen_brightness"), value=1)
    assert evo.sent[-1] == ["0x0202010101"]
    assert _state(hass, "number", "status_led_brightness") == "1"


@pytest.mark.parametrize("key", ["screen_brightness", "status_led_brightness"])
async def test_one_level_needs_the_other_reported_first(hass: HomeAssistant, evo: EvoRobot, key: str) -> None:
    with pytest.raises(HomeAssistantError, match="Panel brightness preset"):
        await _call(hass, "number", "set_value", _eid(hass, "number", key), value=5)
    assert evo.sent == []


async def test_settings_and_actions_publish_their_commands(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.replies = {
        "0x020103000C": ["0x0103000E"],  # change filter reports its own status
        "0x0201220001": ["0x01220000"],  # drawer reset reports 0
    }
    await _call(hass, "select", "select_option", _eid(hass, "select", "cycle_delay"), option="15")
    await _call(hass, "switch", "turn_on", _eid(hass, "switch", "keypad_lockout"))
    await _call(hass, "switch", "turn_off", _eid(hass, "switch", "keypad_lockout"))
    await _call(hass, "switch", "turn_on", _eid(hass, "switch", "weekday_sleep"))
    await _call(hass, "switch", "turn_off", _eid(hass, "switch", "weekday_sleep"))
    await _call(hass, "button", "press", _eid(hass, "button", "start_clean_cycle"))
    await _call(hass, "button", "press", _eid(hass, "button", "start_empty_cycle"))
    await _call(hass, "button", "press", _eid(hass, "button", "start_filter_change"))
    await _call(hass, "button", "press", _eid(hass, "button", "reset_drawer_level"))
    assert evo.sent == [
        ["0x020209000F"],
        ["0x02020A0001"],
        ["0x02020A0000"],
        ["0x020210007F"],
        ["0x0202100000"],
        ["0x020103000A"],
        ["0x020103000B"],
        ["0x020103000C"],
        ["0x0201220001"],
    ]


async def test_the_schedule_times_go_to_every_day(hass: HomeAssistant, evo: EvoRobot) -> None:
    await _call(hass, "time", "set_value", _eid(hass, "time", "panel_sleep_time"), time="22:30:00")
    await _call(hass, "time", "set_value", _eid(hass, "time", "panel_wake_time"), time="06:15:00")
    sleep, wake = evo.sent
    assert sleep == [f"0x0202{0x11 + 2 * day:02X}0546" for day in range(7)]
    assert wake == [f"0x0202{0x12 + 2 * day:02X}0177" for day in range(7)]
    assert _state(hass, "time", "panel_sleep_time") == "22:30:00"
    assert _state(hass, "time", "panel_wake_time") == "06:15:00"


async def test_power_buttons_ship_enabled_and_work(hass: HomeAssistant, evo: EvoRobot) -> None:
    registry = er.async_get(hass)
    for key in ("power_on", "power_off"):
        entry = registry.async_get(_eid(hass, "button", key))
        assert entry is not None and entry.disabled_by is None
    await _call(hass, "button", "press", _eid(hass, "button", "power_off"))
    await _call(hass, "button", "press", _eid(hass, "button", "power_on"))
    assert evo.sent[-2:] == [["0x0201140000"], ["0x0201140001"]]
    assert _state(hass, "binary_sensor", "power") == "on"


async def test_a_setting_the_robot_applied_differently_is_an_error(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.replies = {"0x0202090003": ["0x01020016", "0x02090007"]}
    with pytest.raises(HomeAssistantError, match="applied 0x0007"):
        await _call(hass, "select", "select_option", _eid(hass, "select", "cycle_delay"), option="3")


async def test_an_unanswered_write_is_retried_then_reported(hass: HomeAssistant, evo: EvoRobot) -> None:
    evo.echo = False
    with (
        patch.object(evo_coordinator_module, "_ECHO_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="not acknowledged"),
    ):
        await _call(hass, "button", "press", _eid(hass, "button", "start_clean_cycle"))
    assert evo.sent == [["0x020103000A"], ["0x020103000A"]]


async def test_a_reply_at_another_address_does_not_acknowledge_a_write(
    hass: HomeAssistant, evo: EvoRobot
) -> None:
    evo.replies = {"0x020103000A": ["0x01020014"]}
    with (
        patch.object(evo_coordinator_module, "_ECHO_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="not acknowledged"),
    ):
        await _call(hass, "button", "press", _eid(hass, "button", "start_clean_cycle"))


async def test_a_read_started_while_one_waits_replaces_its_retry(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry
) -> None:
    evo.registers = {}
    coordinator = mock_evo_config_entry.runtime_data
    await coordinator.async_read_state()
    await coordinator.async_read_state()
    assert evo.sent == [_READ_ALL, _READ_ALL]
    await _advance(hass, _AFTER_READ_TIMEOUT)
    assert evo.sent == [_READ_ALL] * 3
    await _advance(hass, _AFTER_READ_TIMEOUT)
    assert evo.sent == [_READ_ALL] * 3


# --- diagnostics --------------------------------------------------------------
async def test_evo_diagnostics_redact_the_serial(
    hass: HomeAssistant, evo: EvoRobot, mock_evo_config_entry: MockConfigEntry
) -> None:
    evo.push(["0x02010808", "0x02100041"])
    await hass.async_block_till_done()
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_evo_config_entry)
    assert EVO_SERIAL not in json.dumps(diagnostics)
    assert diagnostics["available"] is True
    assert diagnostics["state"]["registers"]["0x0201"] == "0x0808"
    assert diagnostics["state"]["sleep_days"] == ["saturday", "sunday"]
