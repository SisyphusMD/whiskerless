# #64 Mirror the Homebrew bottles to the NAS

- Kind: pull, state: closed, by cody, created 2026-08-27T18:46:11-07:00
- Labels: none; milestone: none
- refs/pull/64/head -> main, merged: True

The NAS was missing the 8 bottle assets the cluster and GitHub both carry, so it was not the complete mirror it is meant to be. A separate nas-bottles job copies them once the bottle block lands — separate from nas-bridge on purpose, because that job is ordered ahead of reconcile and prune-rcs while bottles arrive ~13 minutes later. Bottles still stay out of reconcile: a rebuilt bottle differs by its gzip timestamp, so a byte-quorum would call a healthy release a conflict. Copying is not comparing. The manual bottle-rebuild path refreshes the NAS too, and the runbook no longer says bottles are excluded from it.
