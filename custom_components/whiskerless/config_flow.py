"""Config flow for the Whiskerless integration.

Robots are discovered over MQTT: when a Litter-Robot publishes to the broker
Home Assistant's MQTT integration is connected to, it shows up as a discovered
device the user can Add or Ignore — no broker details, no serial to type. The
manual "Add Integration" entry just explains that setup is discovery-driven.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import TextSelector
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import CONF_SERIAL, DEFAULT_NAME, DOMAIN


def _serial_from_topic(topic: str) -> str | None:
    """Extract the serial from a `prod/LR4/<serial>/...` topic."""
    parts = topic.split("/")
    return parts[2] if len(parts) >= 3 and parts[2] else None


class WhiskerlessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Whiskerless."""

    VERSION = 1

    def __init__(self) -> None:
        self._serial: str | None = None

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """Handle a robot discovered on the MQTT broker."""
        serial = _serial_from_topic(discovery_info.topic)
        if serial is None:
            return self.async_abort(reason="invalid_discovery_info")
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        self._serial = serial
        self.context["title_placeholders"] = {"name": f"Litter-Robot 4 ({serial})"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered robot and let the user name it.

        Naming the robot here sets its device name, so its entity_ids are
        generated from that name at creation — handy when you have several.
        """
        assert self._serial is not None
        if user_input is not None:
            name = user_input[CONF_NAME].strip() or DEFAULT_NAME
            return self.async_create_entry(
                title=name, data={CONF_SERIAL: self._serial, CONF_NAME: name}
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector()}),
            description_placeholders={"serial": self._serial},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add is unsupported — robots are discovered automatically."""
        return self.async_abort(reason="discovery_only")
