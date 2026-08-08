"""The Whiskerless integration — local control for Whisker devices."""

from __future__ import annotations

from awesomeversion import AwesomeVersion
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from . import binary_sensor, button, number, select, sensor, switch
from . import time as time_platform
from .const import DOMAIN
from .coordinator import WhiskerlessConfigEntry, WhiskerlessCoordinator

# Option key recording which version last swept the entity registry.
_SWEPT_BY = "retired_entities_swept_by"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


def _producible_entities(serial: str) -> set[tuple[str, str]]:
    """Every ``(domain, unique_id)`` this version can create for ``serial``.

    Keyed by domain as well as unique_id because that is how the registry
    identifies an entity: the same key moved between domains is a different
    entity, and the old one has to go.

    Deliberately the union of what the platforms *can* build, not what they did
    build on this run: entities that only appear once their hardware is detected
    must survive a startup that happens before detection.
    """
    by_domain: dict[str, set[str]] = {
        Platform.BINARY_SENSOR: {
            *(d.key for d in binary_sensor.BINARY_SENSORS),
            *binary_sensor.STANDALONE_KEYS,
        },
        Platform.BUTTON: {d.key for d in button.BUTTONS},
        Platform.NUMBER: {d.key for d in number.NUMBERS},
        Platform.SELECT: {d.key for d in select.SELECTS},
        Platform.SENSOR: {
            *(d.key for d in sensor.SENSORS),
            *(d.key for d in sensor.DATA_SENSORS),
        },
        Platform.SWITCH: {d.key for d in switch.SWITCHES},
        Platform.TIME: {d.key for d in time_platform.TIMES},
    }
    return {
        (domain, f"{serial}_{key}") for domain, keys in by_domain.items() for key in keys
    }


async def _remove_retired_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Drop registry entries for entities this version no longer produces.

    Home Assistant keeps an entity in the registry forever once created, so a
    capability we withdraw (or move to another domain) would otherwise linger as
    a permanently unavailable entity that the user has to delete by hand.

    Skipped when the registry was last swept by a NEWER version, i.e. after a
    downgrade: to an older build every entity the newer one added looks retired,
    and reaping them would throw away the user's entity IDs, names, areas and
    enabled states for entities that come straight back on the way forward.
    """
    running = (await async_get_integration(hass, DOMAIN)).version
    swept = entry.options.get(_SWEPT_BY)
    if running is None or (swept is not None and AwesomeVersion(swept) > running):
        return

    registry = er.async_get(hass)
    producible = _producible_entities(entry.runtime_data.serial)
    for existing in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (existing.domain, existing.unique_id) not in producible:
            registry.async_remove(existing.entity_id)

    if swept != str(running):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, _SWEPT_BY: str(running)}
        )


async def async_setup_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Set up Whiskerless from a config entry."""
    coordinator = WhiskerlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await _remove_retired_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Unload a Whiskerless config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
