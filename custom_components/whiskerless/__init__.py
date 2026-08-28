"""The Whiskerless integration — local control for Whisker devices."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from awesomeversion import AwesomeVersion
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.loader import async_get_integration

from whiskerless.devices.litter_robot_4 import derive
from whiskerless.devices.litter_robot_4.calibration import HOPPER_PLAUSIBLE
from whiskerless.devices.litter_robot_4.derive import Capability, Evidence

from . import binary_sensor, button, number, select, sensor, switch
from . import time as time_platform
from .const import (
    CONF_DERIVED,
    CONF_HOPPER_FILL_RAW,
    CONF_HOPPER_SEEN,
    CONF_SERIAL,
    DOMAIN,
    LOGGER,
)
from .coordinator import SIGHTING_OPTIONS, WhiskerlessConfigEntry, WhiskerlessCoordinator

# Option key recording which version last swept the entity registry.
_SWEPT_BY = "retired_entities_swept_by"
# The retired global "re-check every detection" counter, and the last revision it
# ever reached. Read once (to see which one-off sweeps an install ran) and then
# left pinned there, so a downgrade does not re-run them.
_DETECTION_RESET_BY = "detection_reset_by"
_LAST_SWEEP = 3

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

# Register 0xBC, which some robots never emit — not a firmware split, since two
# robots on the same build sit either side of it. Same treatment for the same
# reason: better absent than permanently unknown on hardware that lacks it.
VISIT_DURATION_ENTITIES: tuple[tuple[str, str], ...] = (
    (Platform.SENSOR, "last_visit_duration"),
)

# The remaining event-only facts, gated on the same principle: 0x56 only fires
# when a drawer is seated, and one live robot has never emitted a weight, so each
# of these can be a permanent unknown on real hardware.
DRAWER_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "waste_drawer_last_moved"),)
PET_WEIGHT_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "pet_weight"),)
CAT_VISIT_ENTITIES: tuple[tuple[str, str], ...] = ((Platform.SENSOR, "last_cat_visit"),)

#: Every capability that ships disabled until the robot proves it has one, and
#: the entities its sighting switches on. Which option records the sighting is
#: the coordinator's table; what counts as proof is the library's.
_DETECTED: dict[Capability, tuple[tuple[str, str], ...]] = {
    Capability.HOPPER: HOPPER_ENTITIES,
    Capability.VISIT_DURATION: VISIT_DURATION_ENTITIES,
    Capability.DRAWER: DRAWER_ENTITIES,
    Capability.PET_WEIGHT: PET_WEIGHT_ENTITIES,
    Capability.CAT_VISIT: CAT_VISIT_ENTITIES,
}

#: Where a re-examined sighting may find its own past reports. Only the entity
#: whose value that capability alone can produce counts — for the hopper that is
#: the fill gauge, not `hopper_connected`, which older builds granted from a
#: 0x57 link report that proves nothing (a positive arrives with the hopper
#: sitting on a bench). Whether a RESTORED sighting is good enough at all is
#: ACCEPTED_EVIDENCE's call, not this table's.
_RESTORE_PROOF: dict[Capability, tuple[tuple[str, str], ...]] = {
    Capability.HOPPER: ((Platform.SENSOR, "hopper_fill"),),
    Capability.VISIT_DURATION: VISIT_DURATION_ENTITIES,
    Capability.DRAWER: DRAWER_ENTITIES,
    Capability.PET_WEIGHT: PET_WEIGHT_ENTITIES,
    Capability.CAT_VISIT: CAT_VISIT_ENTITIES,
}


def _plausible_gauge(*values: object) -> int | None:
    """The first value that looks like a real dispense fill gauge, or None.

    Narrows the legacy-cache weakness described above: a genuine phase-1 gauge
    lands in the same band the calibrator trusts, while a lone register read can
    return anything, including 0.
    """
    low, high = HOPPER_PLAUSIBLE
    for value in values:
        try:
            gauge = int(float(str(value)))
        except (TypeError, ValueError):
            continue
        if low <= gauge <= high:
            return gauge
    return None


def _seed_missing_gauge(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Carry a restored fill gauge into the persisted option, at every setup.

    Installs whose hopper was proven before the gauge was persisted have the
    reading only in the raw sensor's restore cache — so after any restart the
    level sensor sits unknown beside a raw gauge showing a real number, until
    the next dispense (which can be days away). The re-examination above only
    carries the gauge when it runs at all; this is the same carry for the
    ordinary startup. One-time in effect: once the option exists, nothing here
    writes again.
    """
    if not entry.options.get(CONF_HOPPER_SEEN) or CONF_HOPPER_FILL_RAW in entry.options:
        return
    registry = er.async_get(hass)
    domain, key = _RESTORE_PROOF[Capability.HOPPER][0]
    entity_id = registry.async_get_entity_id(
        domain, DOMAIN, f"{entry.data[CONF_SERIAL]}_{key}"
    )
    stored = restore_state.async_get(hass).last_states.get(entity_id) if entity_id else None
    if stored is None:
        return
    extra = stored.extra_data.as_dict() if stored.extra_data else {}
    gauge = _plausible_gauge(stored.state.state, extra.get("native_value"))
    if gauge is None:
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_HOPPER_FILL_RAW: gauge}
    )


def _recheck_sightings(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Re-examine any sighting the current standard of proof no longer accepts.

    What proves a capability has changed twice — the 0x0C dispense burst was
    narrowed, then the 0x57 link report was retired outright — and each change
    used to force a global re-sweep of every install, because a sighting
    recorded only THAT it happened. That was blunt in both directions: it
    re-examined sightings the change had nothing to say about, and it cost a
    correct install its hopper entities for however long the robot took to
    dispense again.

    Now each sighting carries its evidence, so a change to ACCEPTED_EVIDENCE
    invalidates exactly the sightings it disagrees with. One that no longer
    stands is re-derived from that capability's own past reports before being
    withdrawn: the restore cache first, then the persisted gauge, which outlives
    the cache's expiry. Whatever cannot be re-derived goes back to disabled
    until the robot proves it again.

    The same past reports also RECORD a sighting that was never written down,
    which is how an install from before sightings existed keeps entities it
    genuinely earned. Nothing else touches a capability with no sighting: an
    enabled entity without one is then the user's own hand, and no change to
    the rules may revert that.
    """
    registry = er.async_get(hass)
    last_states = restore_state.async_get(hass).last_states
    # From entry data, not runtime_data: this runs BEFORE the coordinator is
    # built, so the coordinator reads the post-sweep flags and a re-proving
    # report can re-sight in the same session.
    serial = entry.data[CONF_SERIAL]
    options = dict(entry.options)
    # The retired global counter, on its last errand: it is the only record of
    # WHICH of the one-off sweeps an install actually ran, and one that never
    # reached the last of them still carries a hopper granted by a 0x57 link
    # report — which proves nothing, since a positive arrives with the hopper
    # sitting on a bench. Those unlabelled sightings are re-examined once here;
    # the rest are labelled, and the marker goes.
    swept_at = int(options.get(_DETECTION_RESET_BY) or 0)
    unvalidated = {
        capability
        for capability, sweep in ((Capability.HOPPER, 3), (Capability.VISIT_DURATION, 1))
        if swept_at < sweep
    }
    # Left behind deliberately, at the last revision that existed. Nothing here
    # reads it again, but a downgrade would see a missing marker as "never
    # swept" and re-run a sweep that clears a visit duration it cannot restore.
    options[_DETECTION_RESET_BY] = max(swept_at, _LAST_SWEEP)
    for capability, entities in _DETECTED.items():
        seen_key = SIGHTING_OPTIONS[capability]
        stored = options.get(seen_key)
        if isinstance(stored, str):
            if derive.sighting_stands(capability, stored):
                continue
        elif stored and capability not in unvalidated:
            # Label it, so this migration never runs a second time.
            options[seen_key] = str(Evidence.LEGACY)
            continue
        # Whether a capability's own past reports are proof at all is the
        # evidence table's call: a restored visit duration is not, because the
        # builds that recorded one did so from evidence since proven wrong.
        if derive.sighting_stands(capability, Evidence.RESTORED) and _reproved(
            capability, serial, registry, last_states, options
        ):
            options[seen_key] = str(Evidence.RESTORED)
            continue
        if not stored:
            continue  # never proven, so there is nothing to withdraw
        options.pop(seen_key, None)
        for domain, key in entities:
            entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
            if entity_id is None:
                continue
            existing = registry.async_get(entity_id)
            if existing is not None and existing.disabled_by is None:
                registry.async_update_entity(
                    entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
    if options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=options)


def _reproved(
    capability: Capability,
    serial: str,
    registry: er.EntityRegistry,
    last_states: Mapping[str, restore_state.StoredState],
    options: dict[str, Any],
) -> bool:
    """Whether this capability's own past reports still prove it."""
    if capability is Capability.HOPPER and options.get(CONF_HOPPER_FILL_RAW) is not None:
        # Written only by builds that already had the multi-reading gate, so its
        # provenance is sound without the band check below.
        return True
    for domain, key in _RESTORE_PROOF.get(capability, ()):
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
        stored = last_states.get(entity_id) if entity_id else None
        if stored is None:
            continue
        # A sensor unavailable at the last shutdown still carries its real
        # native value in the restore extra data — that is evidence too, and
        # demoting on the rendered state alone would hide a sensor whose fact
        # may be rare or never recur.
        extra = stored.extra_data.as_dict() if stored.extra_data else {}
        if capability is Capability.HOPPER:
            gauge = _plausible_gauge(stored.state.state, extra.get("native_value"))
            if gauge is None:
                continue
            # Carry the reading across, not just the flag: the coordinator reads
            # its gauge from the option, and a robot that has not dispensed
            # since would otherwise come back with the level sensor at unknown
            # while the raw gauge beside it restores a real number.
            options.setdefault(CONF_HOPPER_FILL_RAW, gauge)
            return True
        if stored.state.state not in ("unknown", "unavailable") or extra.get("native_value"):
            return True
    return False


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
    for capability, entities in _DETECTED.items():
        if not entry.options.get(SIGHTING_OPTIONS[capability]):
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
#:
#: The calibration buttons went the OTHER way (they now ship disabled, since the
#: robot calibrates itself) and are deliberately absent: promoting them here
#: would re-enable on every startup the very entities the platform now hides.
#: Nothing demotes them either — an install where someone already calibrated
#: keeps the buttons they have been using.
_NOW_ENABLED_BY_DEFAULT: tuple[tuple[str, str], ...] = (
    ("button", "refresh"),
    # The signal is the field that explains a dropout, and a user debugging one has no
    # reason to suspect a disabled diagnostic entity holds the answer.
    ("sensor", "wifi_rssi"),
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


#: Entities renamed in 0.2.0, as (domain, unique-id key, old entity-id suffix,
#: new one). Home Assistant builds an entity_id from the display name ONCE, at
#: creation, so a rename leaves every existing install on the old id forever —
#: two robots set up a month apart would answer to different names for the same
#: reading, which is worse than either name.
_RENAMED: tuple[tuple[str, str, str, str], ...] = (
    (Platform.BUTTON, "start_clean_cycle", "start_clean_cycle", "clean_cycle"),
    (
        Platform.BUTTON,
        "calibrate_litter_full",
        "calibrate_litter_filled_to_the_line",
        "calibrate_full",
    ),
    (Platform.BUTTON, "calibrate_litter_empty", "calibrate_litter_empty", "calibrate_empty"),
    (Platform.SENSOR, "hopper_fill", "hopper_fill_raw", "hopper_reading"),
    (Platform.SENSOR, "litter_reference", "litter_calibration_reference", "litter_reference"),
)
_RENAMED_BY = "entity_ids_renamed"


def _rename_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Move existing entities onto the new entity_ids, once.

    An entity_id rename is not free: anything referring to the old one — an
    automation, a dashboard card, a script — silently stops matching. It is done
    anyway because the alternative is permanent divergence, with two robots set
    up a month apart answering to different names for the same button.

    Matched on the SUFFIX, and the limit of that is worth stating. The generated
    prefix comes from the device name at the moment the entity was created, so
    renaming a device leaves older entities carrying the old prefix and newer
    ones the new — a real install here has both. Requiring today's generated form
    would therefore skip precisely the oldest entities, which are the ones most
    in need of the migration. The cost is that an id a person chose that happens
    to END with the old suffix is indistinguishable from a generated one and will
    be renamed. That is why every rename is logged at WARNING: a silent id change
    is the kind of thing someone discovers weeks later, in a broken automation.
    """
    if entry.options.get(_RENAMED_BY):
        return
    registry = er.async_get(hass)
    for domain, key, was, now in _RENAMED:
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.runtime_data.serial}_{key}"
        )
        if entity_id is None:
            continue
        object_id = entity_id.split(".", 1)[1]
        # `…_start_clean_cycle_2` is what core generates when a second device
        # shares a name, and it is just as generated as the plain form — the
        # counter moves across to the new id with it.
        match = re.fullmatch(rf"(?P<prefix>.*){re.escape(was)}(?P<counter>_\d+)?", object_id)
        if match is None:
            continue  # ends in something else entirely; leave it alone
        target = f"{domain}.{match['prefix']}{now}{match['counter'] or ''}"
        # Both registers, because an entity without a unique_id has a state but
        # no registry row, and core rejects the rename either way — with a
        # ValueError that would take the whole integration's setup down.
        if target == entity_id or registry.async_get(target) or hass.states.get(target):
            continue
        try:
            registry.async_update_entity(entity_id, new_entity_id=target)
        except ValueError:
            LOGGER.debug("Could not rename %s to %s; leaving it alone", entity_id, target)
            continue
        # The restore cache is keyed by entity_id, so without this the entity
        # comes back `unknown` after the rename: a button forgets when it was
        # last pressed, and the hopper gauge forgets a reading the detection
        # sweep reads as proof the hardware exists.
        cached = restore_state.async_get(hass).last_states
        if entity_id in cached:
            cached[target] = cached.pop(entity_id)
        LOGGER.warning(
            "Renamed %s to %s — update any automation or dashboard that used the old id",
            entity_id,
            target,
        )
    hass.config_entries.async_update_entry(entry, options={**entry.options, _RENAMED_BY: True})


#: Sensors whose displayed unit the integration now states outright, and the
#: unit it states. Both are ToF readings the protocol quotes in millimetres and
#: the docs discuss in millimetres; on an imperial system Home Assistant was
#: rendering them as inches to thirteen decimal places, which is the same number
#: in a form nobody here can check against anything.
_UNIT_PINNED: tuple[tuple[str, str], ...] = (
    (Platform.SENSOR, "litter_level_mm"),
    (Platform.SENSOR, "litter_reference"),
)
_UNITS_PINNED_BY = "sensor_units_pinned"
#: Home Assistant's own slot for what the INTEGRATION suggests, as opposed to the
#: plain `sensor` options, which is where a user's override lives.
_SENSOR_PRIVATE = f"{Platform.SENSOR}.private"


def _pin_sensor_units(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Move the mm sensors to millimetres once, on installs that predate the pin.

    `suggested_unit_of_measurement` only seeds an entity at FIRST registration,
    so without this the change reaches nobody who already has the integration —
    which is everyone it was written for.

    Home Assistant separates the two parties cleanly, and so does this: a unit in
    the `sensor` options is the USER's override and is never touched, while
    `sensor.private` is the integration's own slot. Asking for a refresh there is
    exactly what core does when the unit system changes — the entity re-reads our
    suggestion on its next add and re-pins itself — so this states a preference
    through the supported channel rather than forging a user override.

    One-shot even so, recorded on the entry: someone who switches these back to
    inches without using the per-entity override should not be argued with weekly.
    """
    if entry.options.get(_UNITS_PINNED_BY):
        return
    registry = er.async_get(hass)
    for domain, key in _UNIT_PINNED:
        entity_id = registry.async_get_entity_id(
            domain, DOMAIN, f"{entry.runtime_data.serial}_{key}"
        )
        existing = registry.async_get(entity_id) if entity_id else None
        if entity_id is None or existing is None:
            continue
        if "unit_of_measurement" in existing.options.get(Platform.SENSOR, {}):
            continue  # the user picked a unit for this one; it is theirs
        private = dict(existing.options.get(_SENSOR_PRIVATE, {}))
        private["refresh_initial_entity_options"] = True
        registry.async_update_entity_options(entity_id, _SENSOR_PRIVATE, private)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, _UNITS_PINNED_BY: True}
    )


def _drop_detection_bootstrap(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None:
    """Discard the derived snapshot that bridged the enabling reload.

    It exists only so the entities have a value the instant they appear. Kept
    beyond that it would be re-applied on every startup and clobber the newer
    values the entities restore for themselves.
    """
    if CONF_DERIVED not in entry.options:
        return
    options = {k: v for k, v in entry.options.items() if k != CONF_DERIVED}
    hass.config_entries.async_update_entry(entry, options=options)


async def async_setup_entry(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> bool:
    """Set up Whiskerless from a config entry."""
    _recheck_sightings(hass, entry)
    # After the sweep (which may itself seed the flag and gauge), before the
    # coordinator reads the options.
    _seed_missing_gauge(hass, entry)
    coordinator = WhiskerlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await _remove_retired_entities(hass, entry)
    # Before forwarding, so entries an earlier setup created are built enabled
    # in this same pass rather than only after another reload.
    _enable_detected_entities(hass, entry)
    _promote_newly_default_entities(hass, entry)
    _pin_sensor_units(hass, entry)
    # Before the platforms are forwarded, so entities are added under the name
    # they will keep rather than being created and immediately moved.
    _rename_entities(hass, entry)
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
