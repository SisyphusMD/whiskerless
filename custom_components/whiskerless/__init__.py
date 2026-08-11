"""The Whiskerless integration — local control for Whisker devices."""

from __future__ import annotations

from awesomeversion import AwesomeVersion
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.loader import async_get_integration

from . import binary_sensor, button, number, select, sensor, switch
from . import time as time_platform
from .const import (
    CONF_CAT_VISIT_LAST,
    CONF_CAT_VISIT_SEEN,
    CONF_DETECTION_RESET_BY,
    CONF_DRAWER_LAST,
    CONF_DRAWER_SEEN,
    CONF_HOPPER_LAST,
    CONF_HOPPER_SEEN,
    CONF_PET_WEIGHT_LAST,
    CONF_PET_WEIGHT_SEEN,
    CONF_SERIAL,
    CONF_VISIT_DURATION_LAST,
    CONF_VISIT_DURATION_SEEN,
    DOMAIN,
)
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
    (Platform.SENSOR, "hopper_level"),
    (Platform.SENSOR, "last_hopper_dispensed"),
)

# Register 0xBC, which ESP 1.1.75 has never emitted. Same treatment for the same
# reason: better absent than permanently unknown on the firmware that lacks it.
VISIT_DURATION_ENTITIES: tuple[tuple[str, str], ...] = (
    (Platform.SENSOR, "last_visit_duration"),
)

# The remaining event-only facts, gated on the same principle: 0x56 has never
# been observed on 1.1.75, and one live 1.1.75 robot has never emitted a weight,
# so each of these can be a permanent unknown on real hardware.
DRAWER_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "waste_drawer_last_moved"),)
PET_WEIGHT_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "pet_weight"),)
CAT_VISIT_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "last_cat_visit"),)

#: Every capability that ships disabled until the robot proves it has one, as
#: (option recording the sighting, option holding the readings that bridge the
#: enabling reload, entities to switch on).
_DETECTED: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (CONF_HOPPER_SEEN, CONF_HOPPER_LAST, HOPPER_ENTITIES),
    (CONF_VISIT_DURATION_SEEN, CONF_VISIT_DURATION_LAST, VISIT_DURATION_ENTITIES),
    (CONF_DRAWER_SEEN, CONF_DRAWER_LAST, DRAWER_ENTITIES),
    (CONF_PET_WEIGHT_SEEN, CONF_PET_WEIGHT_LAST, PET_WEIGHT_ENTITIES),
    (CONF_CAT_VISIT_SEEN, CONF_CAT_VISIT_LAST, CAT_VISIT_ENTITIES),
)

#: Groups whose sighting may be seeded from a sensor's restore cache in the
#: one-shot sweep below: a restored value there is a real past report. The
#: hopper and visit-duration flags are deliberately NOT seedable — earlier
#: builds recorded them from evidence since proven wrong, so the restored
#: values themselves are suspect and the hardware must re-prove itself.
_RESTORE_SEEDABLE: frozenset[str] = frozenset(
    {CONF_DRAWER_SEEN, CONF_PET_WEIGHT_SEEN, CONF_CAT_VISIT_SEEN}
)


def _reset_unproven_detections(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """One-shot upgrade sweep: every detection must be backed by real evidence.

    Earlier builds recorded a hopper from the 0x0C dispense burst — which a
    hopperless robot emits too — and shipped the event sensors enabled
    unconditionally. Hopper and visit-duration sightings are cleared outright
    (the hardware re-proves itself within a visit and re-enables); the newly
    gated sensors are seeded from their restore cache; whatever is still
    unproven goes back to disabled until its first real report.
    """
    if entry.options.get(CONF_DETECTION_RESET_BY):
        return
    registry = er.async_get(hass)
    options = dict(entry.options)
    options.pop(CONF_HOPPER_SEEN, None)
    options.pop(CONF_VISIT_DURATION_SEEN, None)
    last_states = restore_state.async_get(hass).last_states
    # From entry data, not runtime_data: this must run BEFORE the coordinator
    # is built, so the coordinator reads the post-sweep flags and a re-proving
    # 0x57 can re-sight in the same session.
    serial = entry.data[CONF_SERIAL]
    for seen_key, _, entities in _DETECTED:
        if not options.get(seen_key) and seen_key in _RESTORE_SEEDABLE:
            for domain, key in entities:
                entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
                stored = last_states.get(entity_id) if entity_id else None
                if stored is None:
                    continue
                # A sensor unavailable at the last shutdown still carries its
                # real native value in the restore extra data — that is
                # evidence too, and demoting on the rendered state alone would
                # hide a sensor whose fact may be rare or never recur.
                extra = stored.extra_data.as_dict() if stored.extra_data else {}
                if (
                    stored.state.state not in ("unknown", "unavailable")
                    or extra.get("native_value") is not None
                ):
                    options[seen_key] = True
                    break
        if options.get(seen_key):
            continue
        for domain, key in entities:
            entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
            if entity_id is None:
                continue
            existing = registry.async_get(entity_id)
            if existing is not None and existing.disabled_by is None:
                registry.async_update_entity(
                    entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
    options[CONF_DETECTION_RESET_BY] = True
    hass.config_entries.async_update_entry(entry, options=options)


def _enable_detected_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Turn on the entities for every capability this robot has now proved.

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
    if entry.pref_disable_new_entities:
        return False
    flipped = False
    registry = er.async_get(hass)
    for seen_key, _, entities in _DETECTED:
        if not entry.options.get(seen_key):
            continue
        for domain, key in entities:
            entity_id = registry.async_get_entity_id(
                domain, DOMAIN, f"{entry.runtime_data.serial}_{key}"
            )
            if entity_id is None:
                continue
            existing = registry.async_get(entity_id)
            if existing is not None and existing.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                registry.async_update_entity(entity_id, disabled_by=None)
                flipped = True
    return flipped


#: Entities that shipped disabled and are now on by default. Clearing the flag in
#: the platform only affects entities created from here on: one already in the
#: registry keeps its stored disabled_by forever, so an existing install would
#: never see the change.
_NOW_ENABLED_BY_DEFAULT: tuple[tuple[str, str], ...] = (
    ("button", "calibrate_litter_empty"),
    ("button", "refresh"),
)


def _promote_newly_default_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Enable entities that used to default to disabled.

    Only INTEGRATION-disabled entries are touched: someone who turned the entity
    off by hand keeps that decision, and the entry-wide "disable new entities"
    preference still wins.
    """
    if entry.pref_disable_new_entities:
        return
    registry = er.async_get(hass)
    for domain, key in _NOW_ENABLED_BY_DEFAULT:
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.runtime_data.serial}_{key}"
        )
        if entity_id is None:
            continue
        existing = registry.async_get(entity_id)
        if existing is not None and existing.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_id, disabled_by=None)


def _drop_detection_bootstrap(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Discard the one-shot readings that bridged the enabling reload.

    They exist only so the entities have a value the instant they appear. Kept
    beyond that they would be re-applied on every startup and clobber the newer
    values the entities restore for themselves.
    """
    bootstrap = {last_key for _, last_key, _ in _DETECTED}
    if not bootstrap & entry.options.keys():
        return
    options = {k: v for k, v in entry.options.items() if k not in bootstrap}
    hass.config_entries.async_update_entry(entry, options=options)


async def async_setup_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Set up Whiskerless from a config entry."""
    _reset_unproven_detections(hass, entry)
    coordinator = WhiskerlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await _remove_retired_entities(hass, entry)
    # Before forwarding, so entries an earlier setup created are built enabled
    # in this same pass rather than only after another reload.
    _enable_detected_entities(hass, entry)
    _promote_newly_default_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Again, for entries the platforms just created. If that flipped anything a
    # reload is queued, so the bootstrap readings have to survive to seed it.
    if not _enable_detected_entities(hass, entry):
        _drop_detection_bootstrap(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Unload a Whiskerless config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
