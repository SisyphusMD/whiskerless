# #48 Survive a dropped connection while publishing release assets

- Kind: pull, state: closed, by cody, created 2026-08-25T15:59:41-07:00
- Labels: none; milestone: none
- refs/pull/48/head -> main, merged: True

A dropped connection to one forge failed a whole release leg. Three things turned that transient into a terminal error:

- `rel_asset_state` returned `1` both for "the request failed" and for "the metadata is unreadable", so a reset was indistinguishable from a real byte conflict. It now returns `12` for a failed request.
- `rel_verify_uploaded_asset` retried `10` (not visible yet) but returned immediately on `1`. That is what actually failed the last bottle publish: the upload succeeded, the *verify read* was reset, and a failed lookup was treated as a verdict. It now keeps looking on `12`.
- Uploads had no retry at all. `rel_upload_verified` now retries, and re-checks forge state before every attempt, so a write that landed before the connection broke is recognised rather than repeated. No upload is issued without a definite ABSENT verdict.

Retried reads are also written to a file curl can truncate rather than a stdout it cannot rewind, so a body reset mid-response cannot be concatenated with its replacement and parsed as malformed JSON.

`REL_MUTATE` still carries no curl-level retry, which stays correct: curl cannot tell a write that never landed from one that landed and lost its reply. The retry belongs one level up, where it can look first.

Vendored from project-standard v0.1.17. Covered by six new unit tests (each mutation-tested) and the existing release integration suite on both forges.
