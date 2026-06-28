"""Config-flow tests for the MQTT-discovery model."""

from __future__ import annotations

import pytest
from custom_components.whiskerless.const import CONF_SERIAL, DOMAIN
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import MOCK_SERIAL, STATE_TOPIC

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


def _discovery() -> MqttServiceInfo:
    return MqttServiceInfo(
        topic=STATE_TOPIC,
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
