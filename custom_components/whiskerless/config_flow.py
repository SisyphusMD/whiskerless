"""Config flow for the Whiskerless integration.

Robots are discovered over MQTT: when a Litter-Robot publishes to the broker
Home Assistant's MQTT integration is connected to, it shows up as a discovered
device the user can Add or Ignore — no broker details, no serial to type. The
manual "Add Integration" entry just explains that setup is discovery-driven.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .alerts import alert_settings
from .const import CONF_ALERT_SETTINGS, CONF_SERIAL, DEFAULT_NAME, DOMAIN

# (min, max, unit) for each alert threshold on the options page.
_THRESHOLDS: dict[str, tuple[int, int, str]] = {
    "drawer_level_percent": (50, 100, "%"),
    "litter_low_percent": (5, 80, "%"),
    "no_visit_hours": (4, 96, "h"),
    "long_visit_minutes": (1, 30, "min"),
    "frequent_visits_per_hour": (2, 20, "visits"),
    "weight_change_percent": (3, 50, "%"),
    "deep_clean_days": (7, 365, "d"),
    "filter_days": (7, 180, "d"),
    "globe_clean_days": (7, 365, "d"),
}


def _serial_from_topic(topic: str) -> str | None:
    """Extract the serial from a `prod/LR4/<serial>/...` topic."""
    parts = topic.split("/")
    return parts[2] if len(parts) >= 3 and parts[2] else None


class WhiskerlessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Whiskerless."""

    VERSION = 1

    def __init__(self) -> None:
        self._serial: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WhiskerlessOptionsFlow:
        """The alert thresholds the notification events use."""
        return WhiskerlessOptionsFlow()

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """Handle a robot discovered on the MQTT broker."""
        serial = _serial_from_topic(discovery_info.topic)
        if serial is None:
            return self.async_abort(reason="invalid_discovery_info")
        await self.async_set_unique_id(serial)
        # The robot's own state messages re-trigger this discovery; abort without
        # reloading (the default would reload the entry on every state message,
        # since the discovery carries no connection info to act on).
        self._abort_if_unique_id_configured(reload_on_update=False)
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


class WhiskerlessOptionsFlow(OptionsFlow):
    """Edit the alert thresholds; every other option on the entry is kept as it was.

    The entry's options also hold what the integration learned and the alerts it
    has active, so the result merges into them rather than replacing them.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        if user_input is not None:
            chosen = {name: int(value) for name, value in user_input.items()}
            return self.async_create_entry(data={**options, CONF_ALERT_SETTINGS: chosen})
        current = asdict(alert_settings(options))
        schema = {
            vol.Required(name, default=current[name]): NumberSelector(
                NumberSelectorConfig(
                    min=low, max=high, step=1, unit_of_measurement=unit,
                    mode=NumberSelectorMode.BOX,
                )
            )
            for name, (low, high, unit) in _THRESHOLDS.items()
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
