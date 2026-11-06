"""Config flow for the Whiskerless integration.

Robots are discovered over MQTT: when a Litter-Robot publishes to the broker
Home Assistant's MQTT integration is connected to, it shows up as a discovered
device the user can Add or Ignore — no broker details, no serial to type.

The manual "Add Integration" entry offers the one thing that is not discovered:
a cloud bridge, which relays one robot's MQTT to Whisker's cloud as that robot.
Choosing a robot there explains that robots are discovered.
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

from whiskerless import CloudIdentity, ProtocolError, TopicMap, WhiskerlessConnectionError

from .alerts import alert_settings
from .cloud_bridge import identity_paths, is_bridge_entry
from .const import (
    CONF_ALERT_SETTINGS,
    CONF_CLOUD_HOST,
    CONF_CLOUD_PREFIX,
    CONF_IDENTITY_DIR,
    CONF_KIND,
    CONF_LOCAL_PREFIX,
    CONF_SERIAL,
    DEFAULT_CLOUD_HOST,
    DEFAULT_CLOUD_PREFIX,
    DEFAULT_IDENTITY_DIR,
    DEFAULT_LOCAL_PREFIX,
    DEFAULT_NAME,
    DOMAIN,
    KIND_CLOUD_BRIDGE,
)

# (min, max, unit) for each alert threshold on the options page; no unit for an hour of the day.
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
    "urgent_reminder_hours": (0, 48, "h"),
    "morning_reminder_hour": (0, 23, ""),
    "evening_reminder_hour": (0, 23, ""),
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

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Robots have alert thresholds; a cloud bridge has nothing to adjust."""
        return not is_bridge_entry(config_entry)

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
        """Offer a cloud bridge, or explain that robots are discovered."""
        return self.async_show_menu(step_id="user", menu_options=["cloud_bridge", "robot"])

    async def async_step_robot(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add of a robot is unsupported — robots are discovered automatically."""
        return self.async_abort(reason="discovery_only")

    async def async_step_cloud_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the robot, its topics and where its cloud identity is."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {key: str(value).strip().strip("/") for key, value in user_input.items()}
            serial = data[CONF_SERIAL]
            try:
                TopicMap(f"{data[CONF_LOCAL_PREFIX]}/{serial}", f"{data[CONF_CLOUD_PREFIX]}/{serial}")
                if not all((serial, data[CONF_LOCAL_PREFIX], data[CONF_CLOUD_PREFIX])) or "/" in serial:
                    raise ProtocolError(serial)
            except ProtocolError:
                errors["base"] = "invalid_topics"
            else:
                try:
                    await self.hass.async_add_executor_job(
                        CloudIdentity.from_files, *identity_paths(self.hass, data[CONF_IDENTITY_DIR])
                    )
                except WhiskerlessConnectionError:
                    errors[CONF_IDENTITY_DIR] = "identity_unreadable"
                except ProtocolError:
                    errors[CONF_IDENTITY_DIR] = "identity_invalid"
            if not errors:
                await self.async_set_unique_id(f"{KIND_CLOUD_BRIDGE}_{serial}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Cloud bridge {serial}", data={CONF_KIND: KIND_CLOUD_BRIDGE, **data}
                )
        defaults = user_input or {
            CONF_CLOUD_HOST: DEFAULT_CLOUD_HOST,
            CONF_LOCAL_PREFIX: DEFAULT_LOCAL_PREFIX,
            CONF_CLOUD_PREFIX: DEFAULT_CLOUD_PREFIX,
            CONF_IDENTITY_DIR: DEFAULT_IDENTITY_DIR,
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_SERIAL, default=defaults.get(CONF_SERIAL, "")): TextSelector(),
                vol.Required(CONF_CLOUD_HOST, default=defaults[CONF_CLOUD_HOST]): TextSelector(),
                vol.Required(CONF_LOCAL_PREFIX, default=defaults[CONF_LOCAL_PREFIX]): TextSelector(),
                vol.Required(CONF_CLOUD_PREFIX, default=defaults[CONF_CLOUD_PREFIX]): TextSelector(),
                vol.Required(CONF_IDENTITY_DIR, default=defaults[CONF_IDENTITY_DIR]): TextSelector(),
            }
        )
        return self.async_show_form(step_id="cloud_bridge", data_schema=schema, errors=errors)


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
                    min=low, max=high, step=1, mode=NumberSelectorMode.BOX,
                    **({"unit_of_measurement": unit} if unit else {}),
                )
            )
            for name, (low, high, unit) in _THRESHOLDS.items()
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
