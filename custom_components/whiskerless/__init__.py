"""The Whiskerless integration — local control for Whisker devices."""

from __future__ import annotations

from awesomeversion import AwesomeVersion
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from . import binary_sensor, button, number, select, sensor, switch
from . import time as time_platform
from .const import CONF_HOPPER_LAST, CONF_HOPPER_SEEN, DOMAIN
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


# The optional LitterHopper is invisible in the state document, so these ship
# disabled and switch on once the hardware reports.
HOPPER_ENTITIES: tuple[tuple[str, str], ...] = (
    (Platform.BINARY_SENSOR, "hopper_connected"),
    (Platform.BINARY_SENSOR, "hopper_empty"),
    (Platform.SENSOR, "hopper_fill"),
    (Platform.SENSOR, "last_hopper_dispensed"),
)


def _enable_hopper_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Turn on the hopper entities once this robot is known to have one.

    Called twice per setup. Before the platforms are forwarded it catches
    entries an earlier setup created, so they are built enabled in this same
    pass; after, it catches entries the platforms only just created. Returns
    whether anything was flipped after the fact, which means Home Assistant has
    a reload queued and this setup is not the settled one.

    Changing disabled_by makes Home Assistant queue a reload of its own, so the
    first detection costs one extra reload beyond the one the coordinator asks
    for. That is accepted: it happens once in a robot's life, the detection is
    persisted so a failed reload simply retries, and the alternative is deciding
    enablement at entity-registration time, which cannot reach entries that
    already exist.

    Only promotes INTEGRATION-disabled entities. A user who deliberately turned
    one off keeps that choice, and the entry-wide "disable new entities"
    preference is honoured rather than overridden.
    """
    if not entry.options.get(CONF_HOPPER_SEEN) or entry.pref_disable_new_entities:
        return False
    flipped = False
    registry = er.async_get(hass)
    for domain, key in HOPPER_ENTITIES:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.runtime_data.serial}_{key}")
        if entity_id is None:
            continue
        existing = registry.async_get(entity_id)
        if existing is not None and existing.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_id, disabled_by=None)
            flipped = True
    return flipped


def _drop_hopper_bootstrap(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Discard the one-shot readings that bridged the enabling reload.

    They exist only so the entities have a value the instant they appear. Kept
    beyond that they would be re-applied on every startup and clobber the newer
    values the entities restore for themselves.
    """
    if CONF_HOPPER_LAST not in entry.options:
        return
    options = {k: v for k, v in entry.options.items() if k != CONF_HOPPER_LAST}
    hass.config_entries.async_update_entry(entry, options=options)


async def async_setup_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Set up Whiskerless from a config entry."""
    coordinator = WhiskerlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await _remove_retired_entities(hass, entry)
    # Before forwarding, so entries an earlier setup created are built enabled
    # in this same pass rather than only after another reload.
    _enable_hopper_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Again, for entries the platforms just created. If that flipped anything a
    # reload is queued, so the bootstrap readings have to survive to seed it.
    if not _enable_hopper_entities(hass, entry):
        _drop_hopper_bootstrap(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Unload a Whiskerless config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
