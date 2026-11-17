# #203 Setup fails on HA 2026.11: RestoreStateData has no attribute last_states

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:29-08:00
- Labels: none; milestone: none

_Recreated from GitHub issue [#13](https://github.com/SisyphusMD/whiskerless/issues/13), opened by @b12e on 2026-10-28, when the GitHub copy became read-only._

---

### whiskerless version

0.2.0-rc.69 (HA core 2026.11.0b0, HA OS 18.2)

### Which part?

Home Assistant integration

### Robot firmware version

N/A

### What happened?

After updating to HA 2026.11.0b0, the config entry fails to set up:

```
File "/config/custom_components/whiskerless/__init__.py", line 553, in async_setup_entry
    _recheck_sightings(hass, entry)
File "/config/custom_components/whiskerless/__init__.py", line 234, in _recheck_sightings
    last_states = restore_state.async_get(hass).last_states
AttributeError: 'RestoreStateData' object has no attribute 'last_states'
```

### Cause

HA 2026.11 removed `RestoreStateData.last_states`. Stored states are now split into `last_states_by_entity_id` (entities without a registry entry) and `last_states_by_entity_registry_id` (keyed by registry id), and read through a new `async_get_stored_state(entity_id)`. That getter also follows entity_id renames, because the registry id survives a rename. 2026.10.x and older only have `last_states`.

The integration reads `last_states` directly in five places:

- `__init__.py`: `_seed_missing_gauge`, `_recheck_sightings` (passed on to `_reproved`), and `_rename_entities`, which moves the cache entry across a rename
- `coordinator.py`: the restored binary sensor lookup

### Suggested fix

A small compat module that uses `async_get_stored_state` when it exists and falls back to `last_states` otherwise, so the 2025.3 minimum in hacs.json keeps working. The manual cache move on rename is skipped on 2026.11, since core now handles that. I'm running this patch locally on 2026.11.0b0: the entry loads and restored states (e.g. the clean cycle button's last press) come back. I did not run the test suite.

<details>
<summary>Patch</summary>

```diff
diff --git a/custom_components/whiskerless/__init__.py b/custom_components/whiskerless/__init__.py
index 6d2cb7c..e129d76 100644
--- a/custom_components/whiskerless/__init__.py
+++ b/custom_components/whiskerless/__init__.py
@@ -3,7 +3,7 @@
 from __future__ import annotations
 
 import re
-from collections.abc import Mapping
+from collections.abc import Callable
 from typing import Any
 
 from awesomeversion import AwesomeVersion
@@ -28,6 +28,7 @@ from .const import (
     LOGGER,
 )
 from .coordinator import SIGHTING_OPTIONS, WhiskerlessConfigEntry, WhiskerlessCoordinator
+from .restore_compat import move_stored_state, stored_state
 
 # Option key recording which version last swept the entity registry.
 _SWEPT_BY = "retired_entities_swept_by"
@@ -194,7 +195,7 @@ def _seed_missing_gauge(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> N
     entity_id = registry.async_get_entity_id(
         domain, DOMAIN, f"{entry.data[CONF_SERIAL]}_{key}"
     )
-    stored = restore_state.async_get(hass).last_states.get(entity_id) if entity_id else None
+    stored = stored_state(hass, entity_id)
     if stored is None:
         return
     extra = stored.extra_data.as_dict() if stored.extra_data else {}
@@ -231,7 +232,6 @@ def _recheck_sightings(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> No
     the rules may revert that.
     """
     registry = er.async_get(hass)
-    last_states = restore_state.async_get(hass).last_states
     # From entry data, not runtime_data: this runs BEFORE the coordinator is
     # built, so the coordinator reads the post-sweep flags and a re-proving
     # report can re-sight in the same session.
@@ -267,7 +267,7 @@ def _recheck_sightings(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> No
         # evidence table's call: a restored visit duration is not, because the
         # builds that recorded one did so from evidence since proven wrong.
         if derive.sighting_stands(capability, Evidence.RESTORED) and _reproved(
-            capability, serial, registry, last_states, options
+            capability, serial, registry, lambda eid: stored_state(hass, eid), options
         ):
             options[seen_key] = str(Evidence.RESTORED)
             continue
@@ -291,7 +291,7 @@ def _reproved(
     capability: Capability,
     serial: str,
     registry: er.EntityRegistry,
-    last_states: Mapping[str, restore_state.StoredState],
+    lookup: Callable[[str | None], restore_state.StoredState | None],
     options: dict[str, Any],
 ) -> bool:
     """Whether this capability's own past reports still prove it."""
@@ -301,7 +301,7 @@ def _reproved(
         return True
     for domain, key in _RESTORE_PROOF.get(capability, ()):
         entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
-        stored = last_states.get(entity_id) if entity_id else None
+        stored = lookup(entity_id)
         if stored is None:
             continue
         # A sensor unavailable at the last shutdown still carries its real
@@ -472,9 +472,7 @@ def _rename_entities(hass: HomeAssistant, entry: WhiskerlessConfigEntry) -> None
         # comes back `unknown` after the rename: a button forgets when it was
         # last pressed, and the hopper gauge forgets a reading the detection
         # sweep reads as proof the hardware exists.
-        cached = restore_state.async_get(hass).last_states
-        if entity_id in cached:
-            cached[target] = cached.pop(entity_id)
+        move_stored_state(hass, entity_id, target)
         LOGGER.warning(
             "Renamed %s to %s — update any automation or dashboard that used the old id",
             entity_id,
diff --git a/custom_components/whiskerless/coordinator.py b/custom_components/whiskerless/coordinator.py
index 1e24124..f5bc22e 100644
--- a/custom_components/whiskerless/coordinator.py
+++ b/custom_components/whiskerless/coordinator.py
@@ -23,7 +23,6 @@ from homeassistant.core import HomeAssistant, callback
 from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
 from homeassistant.helpers import device_registry as dr
 from homeassistant.helpers import entity_registry as er
-from homeassistant.helpers import restore_state
 from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
 from homeassistant.util import dt as dt_util
 
@@ -73,6 +72,7 @@ from .const import (
     HEARTBEAT_INTERVAL,
     LOGGER,
 )
+from .restore_compat import stored_state
 
 #: Which config-entry option records each capability's first sighting. The
 #: library decides what counts as proof; Home Assistant decides where it is kept.
@@ -200,7 +200,7 @@ class WhiskerlessCoordinator(DataUpdateCoordinator[WhiskerlessData]):
         entity_id = registry.async_get_entity_id(
             Platform.BINARY_SENSOR, DOMAIN, f"{self.serial}_{key}"
         )
-        stored = restore_state.async_get(self.hass).last_states.get(entity_id) if entity_id else None
+        stored = stored_state(self.hass, entity_id)
         if stored is None or stored.state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
             return None
         return stored.state.state == STATE_ON
diff --git a/custom_components/whiskerless/restore_compat.py b/custom_components/whiskerless/restore_compat.py
new file mode 100644
index 0000000..1f9139f
--- /dev/null
+++ b/custom_components/whiskerless/restore_compat.py
@@ -0,0 +1,33 @@
+"""Read the restore-state cache on both sides of the 2026.11 change.
+
+Home Assistant 2026.11 replaced RestoreStateData.last_states (keyed by
+entity_id) with two maps, one keyed by entity registry id, and a getter that
+also follows entity_id renames. Older releases only have the dict.
+"""
+
+from __future__ import annotations
+
+from homeassistant.core import HomeAssistant
+from homeassistant.helpers import restore_state
+
+
+def stored_state(hass: HomeAssistant, entity_id: str | None) -> restore_state.StoredState | None:
+    """The cached state of entity_id, if the restore cache has one."""
+    if not entity_id:
+        return None
+    data = restore_state.async_get(hass)
+    if (getter := getattr(data, "async_get_stored_state", None)) is not None:
+        return getter(entity_id)
+    return data.last_states.get(entity_id)
+
+
+def move_stored_state(hass: HomeAssistant, old: str, new: str) -> None:
+    """Carry a cached state across an entity_id rename.
+
+    Only needed before 2026.11: since then the cache is keyed by registry id,
+    which a rename keeps, and the getter rewrites the stored entity_id.
+    """
+    data = restore_state.async_get(hass)
+    cached = getattr(data, "last_states", None)
+    if cached is not None and old in cached:
+        cached[new] = cached.pop(old)
```

</details>
