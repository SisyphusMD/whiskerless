"""Cloud bridge entries: a toggle, its traffic, and sending through it.

A cloud bridge entry runs :class:`whiskerless.bridge.CloudBridge` for one robot.
Its local side is Home Assistant's own MQTT connection — the integration opens no
broker connection of its own — and its cloud side presents the robot's cloud
identity to Whisker's AWS IoT endpoint. The entry has three entities: a switch
that runs the bridge, a sensor with its connection state, and an event entity
that fires once per relayed message, so the traffic shows in the logbook. The
``send_bridge_message`` action sends a hand-written message either way.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.components.event import EventEntity
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from whiskerless import (
    BridgeDirection,
    BridgeTraffic,
    CloudBridge,
    CloudIdentity,
    SafetyError,
    TopicMap,
    WhiskerlessConnectionError,
    WhiskerlessError,
    cloud_settings,
)

from .const import (
    CONF_BRIDGE_ENABLED,
    CONF_CLOUD_HOST,
    CONF_CLOUD_PREFIX,
    CONF_IDENTITY_DIR,
    CONF_KIND,
    CONF_LOCAL_PREFIX,
    CONF_SERIAL,
    DOMAIN,
    IDENTITY_FILES,
    KIND_CLOUD_BRIDGE,
    LOGGER,
    SERVICE_SEND_BRIDGE_MESSAGE,
)

PLATFORMS: list[Platform] = [Platform.EVENT, Platform.SENSOR, Platform.SWITCH]

#: Reconnect backoff after the cloud drops or refuses the bridge.
RETRY_INITIAL = 5.0
RETRY_MAX = 300.0
#: Messages kept for diagnostics, and the payload length an event carries.
RECENT_TRAFFIC = 50
EVENT_PAYLOAD_MAX = 2048


class BridgeState(StrEnum):
    """The bridge's connection state."""

    OFF = "off"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


type BridgeConfigEntry = ConfigEntry[BridgeRuntime]


def is_bridge_entry(entry: ConfigEntry[Any]) -> bool:
    """Whether ``entry`` is a cloud bridge entry rather than a robot."""
    return bool(entry.data.get(CONF_KIND) == KIND_CLOUD_BRIDGE)


def identity_paths(hass: HomeAssistant, identity_dir: str) -> tuple[Path, Path, Path]:
    """The three identity files, resolved under the Home Assistant config directory."""
    base = Path(hass.config.path(identity_dir))
    root_ca, certificate, key = (base / name for name in IDENTITY_FILES)
    return root_ca, certificate, key


class BridgeRuntime:
    """One running (or stopped) bridge and the state its entities show."""

    def __init__(self, hass: HomeAssistant, entry: BridgeConfigEntry, identity: CloudIdentity) -> None:
        self.hass = hass
        self.entry = entry
        self.serial: str = entry.data[CONF_SERIAL]
        self.topics = TopicMap(
            f"{entry.data[CONF_LOCAL_PREFIX]}/{self.serial}",
            f"{entry.data[CONF_CLOUD_PREFIX]}/{self.serial}",
        )
        self.bridge = CloudBridge(
            cloud_settings(entry.data[CONF_CLOUD_HOST], self.serial, identity),
            self.topics,
            publish_local=self._publish_local,
            on_traffic=self._on_traffic,
            on_connection=self._on_connection,
        )
        self.state = BridgeState.OFF
        self.last_error: str | None = None
        self.recent: deque[BridgeTraffic] = deque(maxlen=RECENT_TRAFFIC)
        self._listeners: list[CALLBACK_TYPE] = []
        self._traffic_listeners: list[Callable[[BridgeTraffic], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._retry = RETRY_INITIAL

    @property
    def enabled(self) -> bool:
        """Whether the user has the bridge switched on."""
        return bool(self.entry.options.get(CONF_BRIDGE_ENABLED, False))

    @property
    def device_info(self) -> DeviceInfo:
        """The bridge's own device, apart from the robot's."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{KIND_CLOUD_BRIDGE}_{self.serial}")},
            name=self.entry.title,
            manufacturer="Whiskerless",
            model="Cloud bridge",
        )

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call ``update`` whenever the state changes; returns the remover."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_add_traffic_listener(self, on_traffic: Callable[[BridgeTraffic], None]) -> CALLBACK_TYPE:
        """Call ``on_traffic`` for every relayed or sent message; returns the remover."""
        self._traffic_listeners.append(on_traffic)
        return lambda: self._traffic_listeners.remove(on_traffic)

    async def async_set_enabled(self, enabled: bool) -> None:
        """Switch the bridge on or off, and remember the choice."""
        options = {**self.entry.options, CONF_BRIDGE_ENABLED: enabled}
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        if enabled:
            await self.async_start()
        else:
            await self.async_stop()

    async def async_start(self) -> None:
        """Subscribe to the robot's local topics and start relaying."""
        if self._task is not None:
            return
        for topic in self.topics.local_subscriptions():
            self._unsubscribe.append(
                await mqtt.async_subscribe(self.hass, topic, self._local_message, qos=1, encoding=None)
            )
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} cloud bridge {self.serial}"
        )

    async def async_stop(self) -> None:
        """Stop relaying and drop the local subscriptions."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        while self._unsubscribe:
            self._unsubscribe.pop()()
        self.last_error = None
        self._set_state(BridgeState.OFF)

    async def _run(self) -> None:
        while True:
            self._set_state(BridgeState.CONNECTING)
            try:
                await self.bridge.run()
                self.last_error = "the cloud closed the connection"
            except WhiskerlessConnectionError as exc:
                self.last_error = str(exc)
            LOGGER.warning("Cloud bridge for %s: %s; retrying in %.0f s", self.serial, self.last_error, self._retry)
            self._set_state(BridgeState.ERROR)
            await asyncio.sleep(self._retry)
            self._retry = min(self._retry * 2, RETRY_MAX)

    async def _publish_local(self, topic: str, payload: bytes) -> None:
        await mqtt.async_publish(self.hass, topic, payload, qos=1)

    @callback
    def _local_message(self, message: ReceiveMessage) -> None:
        payload = message.payload if isinstance(message.payload, bytes) else str(message.payload).encode()
        self.entry.async_create_task(self.hass, self.bridge.from_robot(message.topic, payload))

    @callback
    def _on_connection(self, connected: bool) -> None:
        if connected:
            self._retry = RETRY_INITIAL
            self.last_error = None
            self._set_state(BridgeState.CONNECTED)

    @callback
    def _on_traffic(self, traffic: BridgeTraffic) -> None:
        self.recent.append(traffic)
        for on_traffic in list(self._traffic_listeners):
            on_traffic(traffic)

    @callback
    def _set_state(self, state: BridgeState) -> None:
        self.state = state
        for update in list(self._listeners):
            update()


async def async_setup_bridge_entry(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    """Set up a cloud bridge entry: load the identity, add the entities, resume if on."""
    paths = identity_paths(hass, entry.data[CONF_IDENTITY_DIR])
    try:
        identity = await hass.async_add_executor_job(CloudIdentity.from_files, *paths)
    except WhiskerlessError as exc:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="bridge_identity_unreadable",
            translation_placeholders={"error": str(exc)},
        ) from exc
    runtime = BridgeRuntime(hass, entry, identity)
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if runtime.enabled:
        await runtime.async_start()
    return True


async def async_unload_bridge_entry(hass: HomeAssistant, entry: BridgeConfigEntry) -> bool:
    """Stop the bridge and unload its entities."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# --- entities ------------------------------------------------------------------


class BridgeEntity(Entity):
    """Common base: one device per bridge, pushed state, no polling."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: BridgeRuntime, key: str) -> None:
        self.runtime = runtime
        self._attr_translation_key = key
        self._attr_unique_id = f"{KIND_CLOUD_BRIDGE}_{runtime.serial}_{key}"
        self._attr_device_info = runtime.device_info

    async def async_added_to_hass(self) -> None:
        """Follow the bridge's state changes."""
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))


class BridgeSwitch(BridgeEntity, SwitchEntity):
    """Runs the bridge."""

    @property
    def is_on(self) -> bool:
        return self.runtime.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.async_set_enabled(False)
        self.async_write_ha_state()


class BridgeStateSensor(BridgeEntity, SensorEntity):
    """The bridge's connection state, with the last error while it is retrying."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: BridgeRuntime, key: str) -> None:
        super().__init__(runtime, key)
        self._attr_options = [state.value for state in BridgeState]

    @property
    def native_value(self) -> str:
        return self.runtime.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"last_error": self.runtime.last_error}


class BridgeTrafficEvent(BridgeEntity, EventEntity):
    """Fires once per message the bridge relays or sends."""

    def __init__(self, runtime: BridgeRuntime, key: str) -> None:
        super().__init__(runtime, key)
        self._attr_event_types = [direction.value for direction in BridgeDirection]

    async def async_added_to_hass(self) -> None:
        """Fire on every message, instead of following the connection state."""
        self.async_on_remove(self.runtime.async_add_traffic_listener(self._on_traffic))

    @callback
    def _on_traffic(self, traffic: BridgeTraffic) -> None:
        text = traffic.text()
        self._trigger_event(
            traffic.direction.value,
            {
                "topic": traffic.topic,
                "payload": text[:EVENT_PAYLOAD_MAX],
                "truncated": len(text) > EVENT_PAYLOAD_MAX,
                "injected": traffic.injected,
            },
        )
        self.async_write_ha_state()


@callback
def async_add_bridge_entities(
    entry: BridgeConfigEntry, platform: Platform, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the bridge entity of ``platform`` (the platform modules delegate here)."""
    runtime = entry.runtime_data
    entity: Entity
    if platform is Platform.SWITCH:
        entity = BridgeSwitch(runtime, "cloud_bridge")
    elif platform is Platform.SENSOR:
        entity = BridgeStateSensor(runtime, "cloud_bridge_state")
    else:
        entity = BridgeTrafficEvent(runtime, "cloud_bridge_traffic")
    async_add_entities([entity])


# --- the send action -------------------------------------------------------------

SEND_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("direction"): vol.In([direction.value for direction in BridgeDirection]),
        vol.Required("payload"): cv.string,
        vol.Optional("topic_leaf"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_-]+$")),
        vol.Optional("allow_untraced", default=False): cv.boolean,
    }
)


@callback
def async_register_bridge_actions(hass: HomeAssistant) -> None:
    """Register ``whiskerless.send_bridge_message``."""

    async def send(call: ServiceCall) -> None:
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if entry is None or entry.domain != DOMAIN or not is_bridge_entry(entry):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="bridge_not_found")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="bridge_not_loaded")
        runtime = cast(BridgeConfigEntry, entry).runtime_data
        try:
            await runtime.bridge.send(
                BridgeDirection(call.data["direction"]),
                call.data["payload"].encode(),
                leaf=call.data.get("topic_leaf"),
                allow_untraced=call.data["allow_untraced"],
            )
        except SafetyError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="bridge_command_refused",
                translation_placeholders={"error": str(exc)},
            ) from exc
        except WhiskerlessConnectionError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_offline",
                translation_placeholders={"error": str(exc)},
            ) from exc

    hass.services.async_register(DOMAIN, SERVICE_SEND_BRIDGE_MESSAGE, send, schema=SEND_SCHEMA)
