"""Config-flow tests for the MQTT-discovery model."""

from __future__ import annotations

import pytest
from custom_components.whiskerless.const import CONF_SERIAL, DEFAULT_NAME, DOMAIN
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import MOCK_SERIAL, STATE_TOPIC

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


def _discovery(topic: str = STATE_TOPIC) -> MqttServiceInfo:
    return MqttServiceInfo(
        topic=topic,
        payload="{}",
        qos=1,
        retain=False,
        subscribed_topic="prod/LR4/+/state",
        timestamp=0.0,
    )


async def test_discovery_flow(hass: HomeAssistant) -> None:
    """A discovered robot offers a confirm/name form, then creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Upstairs litterbox"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MOCK_SERIAL
    assert result["data"] == {CONF_SERIAL: MOCK_SERIAL, CONF_NAME: "Upstairs litterbox"}


@pytest.mark.parametrize("topic", ["prod/LR4//state", "prod/LR4", "prod"])
async def test_discovery_without_a_serial_aborts(hass: HomeAssistant, topic: str) -> None:
    """A discovery whose topic carries no serial is refused, not guessed at."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery(topic)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery_info"


@pytest.mark.parametrize("name", ["", "   "])
async def test_blank_name_falls_back_to_the_default(hass: HomeAssistant, name: str) -> None:
    """A blank name would otherwise produce an unnamed device and bare entity IDs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: name}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == {CONF_SERIAL: MOCK_SERIAL, CONF_NAME: DEFAULT_NAME}


async def test_discovery_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A re-announced robot that is already set up aborts."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_discovery()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_step_is_discovery_only(hass: HomeAssistant) -> None:
    """Manual add explains that robots are discovered automatically."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "discovery_only"
