# #67 Drop the bottle-build curl retry count

- Kind: pull, state: closed, by cody, created 2026-08-27T23:15:32-07:00
- Labels: none; milestone: none
- refs/pull/67/head -> main, merged: True

Raising HOMEBREW_CURL_RETRIES to 8 made every platform in one run sit over an hour without finishing a bottle, against ~14 minutes for the whole run without it. The count multiplies the wait exactly when ghcr is broadly slow. The failure it guarded costs one platform and gh run rerun --failed rebuilds just that job. The formula smoke keeps 8 because it is paired with the pull-through mirror; there is no mirror here.
