# #30 Retry every install-matrix fetch, including a failed name lookup

- Kind: pull, state: closed, by cody, created 2026-08-23T20:26:43-07:00
- Labels: none; milestone: none
- refs/pull/30/head -> main, merged: True

A candidate died on `curl: (6) Could not resolve host: astral.sh` while fetching the uv installer. The infra-retry workflow correctly declined to rescue it — the failure was inside one of our own steps, which is exactly what that workflow refuses to launder into green. So the fix belongs on the fetch.

- every network fetch in the install path now retries
- the installer is written to a file, never piped: curl cannot rewind a pipe, so a retried partial body would reach `sh` concatenated with the first
- container fetches retry in the shell via `packaging/fetch.sh`, because `--retry` alone does not cover a name-resolution failure and Rocky 8 ships curl 7.61, which rejects `--retry-all-errors` outright
- an invariant pins all of it, mirrored into the sibling
