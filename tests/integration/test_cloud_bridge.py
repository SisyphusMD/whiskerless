"""Cloud bridge entries: setup, the toggle, traffic, the send action, diagnostics.

The cloud side is faked by replacing ``CloudBridge.run``; the local side is Home
Assistant's MQTT, mocked by the ``mqtt_mock`` fixture. The identity files hold
placeholder PEM text.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from custom_components.whiskerless import cloud_bridge
from custom_components.whiskerless.cloud_bridge import BridgeState
from custom_components.whiskerless.config_flow import WhiskerlessConfigFlow
from custom_components.whiskerless.const import (
    CONF_BRIDGE_ENABLED,
    CONF_CLOUD_HOST,
    CONF_CLOUD_PREFIX,
    CONF_IDENTITY_DIR,
    CONF_KIND,
    CONF_LOCAL_PREFIX,
    CONF_SERIAL,
    DEFAULT_IDENTITY_DIR,
    DOMAIN,
    KIND_CLOUD_BRIDGE,
    SERVICE_SEND_BRIDGE_MESSAGE,
)
from custom_components.whiskerless.diagnostics import async_get_config_entry_diagnostics
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from whiskerless.bridge import BridgeDirection, CloudBridge
from whiskerless.exceptions import WhiskerlessConnectionError

from .const import MOCK_SERIAL

pytestmark = pytest.mark.usefixtures("mqtt_mock")

LOCAL = f"prod/LR4/{MOCK_SERIAL}"
CLOUD = f"prod/robots/{MOCK_SERIAL}"
SWITCH = "switch.cloud_bridge_lr4c000001_cloud_bridge"
SENSOR = "sensor.cloud_bridge_lr4c000001_cloud_bridge_state"
EVENT = "event.cloud_bridge_lr4c000001_cloud_bridge_traffic"
PEM = "-----BEGIN {0}-----\nU1lOVEhFVElD\n-----END {0}-----\n"
BRIDGE_DATA = {
    CONF_KIND: KIND_CLOUD_BRIDGE,
    CONF_SERIAL: MOCK_SERIAL,
    CONF_CLOUD_HOST: "iot.invalid",
    CONF_LOCAL_PREFIX: "prod/LR4",
    CONF_CLOUD_PREFIX: "prod/robots",
    CONF_IDENTITY_DIR: DEFAULT_IDENTITY_DIR,
}


@pytest.fixture(autouse=True)
def _own_config_dir(hass: HomeAssistant, tmp_path: Path) -> None:
    """Give each test its own config folder; the default one is shared across tests."""
    hass.config.config_dir = str(tmp_path)


def _write_identity(hass: HomeAssistant, folder: str = DEFAULT_IDENTITY_DIR, *, key: str | None = None) -> Path:
    base = Path(hass.config.path(folder))
    base.mkdir(parents=True, exist_ok=True)
    (base / "root_ca.pem").write_text(PEM.format("CERTIFICATE"))
    (base / "device.crt").write_text(PEM.format("CERTIFICATE"))
    (base / "device.key").write_text(key if key is not None else PEM.format("RSA PRIVATE KEY"))
    return base


def _bridge_entry(**options: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Cloud bridge {MOCK_SERIAL}",
        unique_id=f"{KIND_CLOUD_BRIDGE}_{MOCK_SERIAL}",
        data=dict(BRIDGE_DATA),
        options=options,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _fake_cloud(*outcomes: Exception | None) -> Callable[[CloudBridge], Any]:
    """A stand-in for CloudBridge.run: each call takes the next outcome.

    An exception is raised; ``None`` connects and stays up. When the outcomes run
    out, the call returns, as when the cloud closes the connection.
    """
    queue = list(outcomes)

    async def run(self: CloudBridge) -> None:
        if not queue:
            return
        outcome = queue.pop(0)
        if outcome is not None:
            raise outcome
        assert self._on_connection is not None
        self._on_connection(True)
        await asyncio.Event().wait()

    return run


async def _until(hass: HomeAssistant, entity_id: str, state: str) -> None:
    for _ in range(100):
        await hass.async_block_till_done()
        current = hass.states.get(entity_id)
        if current is not None and current.state == state:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{entity_id} never reached {state}: {hass.states.get(entity_id)}")


# --- config flow -----------------------------------------------------------------


async def _bridge_form(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "cloud_bridge"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cloud_bridge"
    return result


def _user_input(**overrides: str) -> dict[str, str]:
    data = {key: value for key, value in BRIDGE_DATA.items() if key != CONF_KIND}
    return {**data, **overrides}


async def test_flow_creates_a_bridge_entry(hass: HomeAssistant) -> None:
    _write_identity(hass)
    result = await _bridge_form(hass)
    with patch("custom_components.whiskerless.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _user_input(local_prefix="prod/LR4/", serial=f" {MOCK_SERIAL} ")
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Cloud bridge {MOCK_SERIAL}"
    assert result["data"] == BRIDGE_DATA  # trimmed: no stray slashes or spaces
    assert result["result"].unique_id == f"{KIND_CLOUD_BRIDGE}_{MOCK_SERIAL}"


@pytest.mark.parametrize(
    "overrides",
    [{"serial": "LR4C/000001"}, {"cloud_prefix": "prod/+"}, {"local_prefix": ""}],
)
async def test_flow_rejects_unusable_topics(hass: HomeAssistant, overrides: dict[str, str]) -> None:
    result = await _bridge_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input(**overrides))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_topics"}


async def test_flow_rejects_a_missing_identity(hass: HomeAssistant) -> None:
    result = await _bridge_form(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(identity_dir="whiskerless/nowhere")
    )
    assert result["errors"] == {CONF_IDENTITY_DIR: "identity_unreadable"}


async def test_flow_rejects_an_identity_that_is_not_pem(hass: HomeAssistant) -> None:
    _write_identity(hass, key="not a key")
    result = await _bridge_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["errors"] == {CONF_IDENTITY_DIR: "identity_invalid"}


async def test_flow_refuses_a_second_bridge_for_the_same_robot(hass: HomeAssistant) -> None:
    _write_identity(hass)
    _bridge_entry().add_to_hass(hass)
    result = await _bridge_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _user_input())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_only_robots_have_an_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    assert WhiskerlessConfigFlow.async_supports_options_flow(mock_config_entry) is True
    assert WhiskerlessConfigFlow.async_supports_options_flow(_bridge_entry()) is False


# --- setup and the toggle ----------------------------------------------------------


async def test_setup_fails_without_an_identity(hass: HomeAssistant) -> None:
    entry = _bridge_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_a_new_bridge_starts_off(hass: HomeAssistant) -> None:
    _write_identity(hass)
    await _setup(hass, _bridge_entry())
    assert hass.states.get(SWITCH).state == "off"
    assert hass.states.get(SENSOR).state == BridgeState.OFF
    assert hass.states.get(EVENT).state == "unknown"


async def test_switching_on_connects_and_relays_the_robot(hass: HomeAssistant) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    relayed: list[tuple[str, bytes]] = []

    async def from_robot(self: CloudBridge, topic: str, payload: bytes) -> bool:
        relayed.append((topic, payload))
        return True

    with (
        patch.object(CloudBridge, "run", _fake_cloud(None)),
        patch.object(CloudBridge, "from_robot", from_robot),
    ):
        await _setup(hass, entry)
        await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
        await _until(hass, SENSOR, BridgeState.CONNECTED)
        assert entry.options[CONF_BRIDGE_ENABLED] is True
        async_fire_mqtt_message(hass, f"{LOCAL}/activity", b'{"data":["0x0102000016"]}')
        await hass.async_block_till_done()
        assert relayed == [(f"{LOCAL}/activity", b'{"data":["0x0102000016"]}')]

        await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
        await _until(hass, SENSOR, BridgeState.OFF)
        assert entry.options[CONF_BRIDGE_ENABLED] is False
        async_fire_mqtt_message(hass, f"{LOCAL}/activity", b"after")
        await hass.async_block_till_done()
        assert len(relayed) == 1  # unsubscribed with the bridge off


async def test_an_enabled_bridge_resumes_and_retries_after_errors(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_identity(hass)
    monkeypatch.setattr(cloud_bridge, "RETRY_INITIAL", 0.01)
    entry = _bridge_entry(**{CONF_BRIDGE_ENABLED: True})
    failure = WhiskerlessConnectionError(f"cloud connection failed for {MOCK_SERIAL}")
    seen: list[str] = []
    with patch.object(CloudBridge, "run", _fake_cloud(failure, None)):
        entry.add_to_hass(hass)
        hass.bus.async_listen(
            "state_changed",
            lambda event: seen.append(event.data["new_state"].state)
            if event.data["entity_id"] == SENSOR and event.data["new_state"]
            else None,
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await _until(hass, SENSOR, BridgeState.CONNECTED)
        assert BridgeState.ERROR in seen
        runtime = entry.runtime_data
        await runtime.async_start()  # already running: a no-op
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["state"] == BridgeState.CONNECTED
        assert diagnostics["last_error"] is None
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert runtime.state is BridgeState.OFF


async def test_a_closed_connection_is_reported_as_an_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_identity(hass)
    monkeypatch.setattr(cloud_bridge, "RETRY_INITIAL", 60)
    entry = _bridge_entry(**{CONF_BRIDGE_ENABLED: True})
    with patch.object(CloudBridge, "run", _fake_cloud()):
        await _setup(hass, entry)
        await _until(hass, SENSOR, BridgeState.ERROR)
        attributes = hass.states.get(SENSOR).attributes
        assert attributes["last_error"] == "the cloud closed the connection"
        assert await hass.config_entries.async_unload(entry.entry_id)


# --- traffic and the send action -------------------------------------------------------


async def test_sending_to_the_robot_fires_a_traffic_event(hass: HomeAssistant, mqtt_mock: Any) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    await _setup(hass, entry)
    payload = '{"serial": "LR4C000001", "data": ["0x02010201"]}'
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_BRIDGE_MESSAGE,
        {"config_entry_id": entry.entry_id, "direction": "to_robot", "payload": payload},
        blocking=True,
    )
    await hass.async_block_till_done()
    mqtt_mock.async_publish.assert_called_with(f"{LOCAL}/command", payload.encode(), 1, False)
    state = hass.states.get(EVENT)
    assert state.attributes["event_type"] == BridgeDirection.TO_ROBOT.value
    assert state.attributes["topic"] == f"{LOCAL}/command"
    assert state.attributes["injected"] is True
    assert state.attributes["truncated"] is False
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"][CONF_SERIAL] == "**REDACTED**"
    assert diagnostics["recent_traffic"][0]["topic"] == "prod/LR4/**REDACTED**/command"
    assert "payload" not in diagnostics["recent_traffic"][0]


async def test_long_payloads_are_truncated_in_the_event(hass: HomeAssistant) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    await _setup(hass, entry)
    long = '{"serial": "LR4C000001", "data": ["0x02010201"], "pad": "' + "x" * 3000 + '"}'
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_BRIDGE_MESSAGE,
        {"config_entry_id": entry.entry_id, "direction": "to_robot", "payload": long},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(EVENT)
    assert state.attributes["truncated"] is True
    assert len(state.attributes["payload"]) == cloud_bridge.EVENT_PAYLOAD_MAX


async def test_the_safety_guard_refuses_untraced_commands(hass: HomeAssistant) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    await _setup(hass, entry)
    call = {"config_entry_id": entry.entry_id, "direction": "to_robot", "payload": "raw bytes"}
    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(DOMAIN, SERVICE_SEND_BRIDGE_MESSAGE, call, blocking=True)
    assert refused.value.translation_key == "bridge_command_refused"
    await hass.services.async_call(
        DOMAIN, SERVICE_SEND_BRIDGE_MESSAGE, {**call, "allow_untraced": True}, blocking=True
    )


async def test_sending_to_the_cloud_needs_a_connection(hass: HomeAssistant) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    await _setup(hass, entry)
    with pytest.raises(HomeAssistantError) as offline:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_BRIDGE_MESSAGE,
            {"config_entry_id": entry.entry_id, "direction": "to_cloud", "payload": "{}", "topic_leaf": "state"},
            blocking=True,
        )
    assert offline.value.translation_key == "bridge_offline"


async def test_the_action_names_a_loaded_bridge(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    _write_identity(hass)
    entry = _bridge_entry()
    await _setup(hass, entry)
    mock_config_entry.add_to_hass(hass)  # a robot, not a bridge
    for entry_id, key in (("nope", "bridge_not_found"), (mock_config_entry.entry_id, "bridge_not_found")):
        with pytest.raises(ServiceValidationError) as wrong:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SEND_BRIDGE_MESSAGE,
                {"config_entry_id": entry_id, "direction": "to_robot", "payload": "{}"},
                blocking=True,
            )
        assert wrong.value.translation_key == key
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as unloaded:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_BRIDGE_MESSAGE,
            {"config_entry_id": entry.entry_id, "direction": "to_robot", "payload": "{}"},
            blocking=True,
        )
    assert unloaded.value.translation_key == "bridge_not_loaded"
