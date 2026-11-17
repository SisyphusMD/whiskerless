# #65 Retry the bottle build's network steps

- Kind: pull, state: closed, by cody, created 2026-08-27T20:57:08-07:00
- Labels: none; milestone: none
- refs/pull/65/head -> main, merged: True

A ghcr.io blob that failed to download killed one bottle platform and stranded the tap pass waiting for a manifest that was never coming. bottles.yml set no HOMEBREW_* env at all, while the formula smoke has always set HOMEBREW_CURL_RETRIES=8 for exactly this. Adds it to both legs, and retries the two git-based brew steps (update, tap) that curl retries do not cover. retry.sh moves into the shared standard, since a vendored script may not depend on a file the standard neither ships nor locks.
