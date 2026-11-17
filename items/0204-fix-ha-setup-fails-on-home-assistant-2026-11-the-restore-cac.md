# #204 fix(ha): setup fails on Home Assistant 2026.11 — the restore cache lost `last_states`

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:30-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#17](https://github.com/SisyphusMD/whiskerless/pull/17), opened by @CryingPecan on 2026-11-06, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

## The bug

On Home Assistant **2026.11.0** every config entry fails in `async_setup_entry` and all entities go unavailable:

```
File "custom_components/whiskerless/__init__.py", line 560, in async_setup_entry
    _recheck_sightings(hass, entry)
File "custom_components/whiskerless/__init__.py", line 241, in _recheck_sightings
    last_states = restore_state.async_get(hass).last_states
AttributeError: 'RestoreStateData' object has no attribute 'last_states'
```

2026.11 replaced `RestoreStateData.last_states` (one dict keyed by entity id) with `last_states_by_entity_id` and `last_states_by_entity_registry_id`, read through a new `async_get_stored_state(entity_id)`. The integration reaches into the old dict in four places:

| Where | What it reads the cache for |
|---|---|
| `__init__.py` hopper seed | the restored fill gauge |
| `__init__.py` `_recheck_sightings` / `_reproved` | past reports that still prove a capability |
| `__init__.py` entity rename | moving the cache entry to the new entity id |
| `coordinator.py` latching-sensor seed | the restored `on`/`off` |

The first one that runs raises before the coordinator exists, so nothing after it happens. `main` and `v0.2.0-rc.74` both have these lines.

## Seen live

Two robots on rc.74. Home Assistant updated to 2026.11.0 on 2026-11-05 and both entries went to `setup_error` at the first start. The robots stayed connected to the broker and kept cycling; Home Assistant just could not see them. With this change applied to the installed copy and a core restart, both entries load on 2026.11.0 and every sensor is back. The entries pass through `setup_retry` for about a minute while each robot answers, same as before.

One side effect worth knowing: no live alert fired during the outage. Entities that *start* unavailable never make the transition an "offline" trigger waits for.

## The fix

`coordinator.stored_state(hass, entity_id)` does the lookup: through `async_get_stored_state` where core has it, through the dict where it does not. The hopper seed, the sighting re-check and the latching-sensor seed all go through it.

The rename is the one place that *wrote* to the dict. 2026.11 keys the cache by registry id, so a renamed entity keeps its stored state there without help. The hand move now only happens on a core that still has the dict.

No behavior change on older cores.

## Tests

`pytest-homeassistant-custom-component` still pins `homeassistant==2026.10.4`, so the suite cannot run on a real 2026.11 yet. The new tests in `tests/integration/test_restore_cache_layouts.py` present the 2026.11 layout to the integration by swapping the `restore_state` reference its two modules hold. Core keeps its own reference, so Home Assistant's own restore path is untouched. On a test core that already has the new layout the fixture passes the real object through.

- the lookup uses the accessor when core has one, and the dict when it does not
- a restored fill gauge still proves a hopper under the 2026.11 layout (the two reads that took setup down)
- a latched sensor still restores under it
- a rename does not reach for the old dict under it

Reverting any one call site makes the matching test fail with the same `AttributeError`.

Run locally on Python 3.13 / Home Assistant 2026.2.3:

```
ruff check        All checks passed
mypy              no issues in 29 source files
pytest tests/integration --cov --cov-fail-under=99
                  213 passed, coverage 99.80%
```

## cody, 2026-11-17T08:59:30-08:00

_@CryingPecan on GitHub, 2026-11-14:_

Closing as superseded: fc6898b on main fixes the same `last_states` removal, and it shipped in v0.2.0-rc.75. Thanks for the quick turnaround.
