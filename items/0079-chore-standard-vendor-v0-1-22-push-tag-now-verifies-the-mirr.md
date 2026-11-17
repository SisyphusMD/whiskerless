# #79 chore(standard): vendor v0.1.22 (push-tag now verifies the mirror instead of assuming it synced)

- Kind: pull, state: closed, by cody, created 2026-08-29T11:52:32-07:00
- Labels: none; milestone: none
- refs/pull/79/head -> main, merged: True

`push_mirrors-sync` returns 403 for a repo-scoped token, so the sync call has always been best-effort and the tag push simply assumed it worked. That assumption is what failed dreame rc.41.

v0.1.22 makes `push-tag.sh` poll the mirror for the tag after the sync request and report present, absent, or indeterminate distinctly. A mirror that never catches up warns rather than blocking, since the release itself is already on the source of truth.

Sibling gets the same vendor.
