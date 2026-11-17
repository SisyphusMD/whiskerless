# #27 Re-vendor the standard when Renovate moves the pin

- Kind: pull, state: closed, by cody, created 2026-08-23T15:53:57-07:00
- Labels: none; milestone: none
- refs/pull/27/head -> main, merged: True

Renovate can raise the `PROJECT_STANDARD` pin but cannot fetch the tag it then names, so every standard bump landed red on the drift check and was closed as obsolete.

- `packaging/revendor-standard.sh` reads the pin, clones that tag (bounded by prompt, transfer rate and wall clock) and runs its own `vendor.py`
- `refresh-pins.sh` calls it first, since a bump can replace every other script in `packaging/` including itself
- `fileFilters` widened so Renovate keeps what the re-vendor writes, with a test asserting every path in `STANDARD.lock` is covered
- the standard bump PR note no longer tells reviewers to re-vendor by hand

Standard moved to v0.1.15, which retires files it stops shipping and replaces by rename so a running script survives its own update.
