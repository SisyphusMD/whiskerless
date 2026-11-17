# #41 Do not call CI green until native macOS agrees

- Kind: pull, state: closed, by cody, created 2026-08-24T16:38:52-07:00
- Labels: none; milestone: none
- refs/pull/41/head -> main, merged: True

The Linux suites were the whole CI verdict; macOS ran only on the mirror. A pull request could therefore read green with its macOS matrix red, and nothing noticed until the release gate refused to tag — by which point the commit was already on main. dreame-valetudo has held this gate for a while; this ports it.

Three things the review caught, each fixed and then mutation-tested:

- **It must not run for a tag.** A prerelease stamps a commit pushed only as a tag, and `ci-macos.yml` runs on branch pushes — so no run could ever exist for that sha and the gate would poll to timeout and fail *every prerelease*. dreame escapes this only because its `ci.yml` has no tag trigger; whiskerless's does.
- **No write credential.** The checkout persisted the repository token where a script from a PR-controlled ref runs beside it. Now `persist-credentials: false`, matching the release mirror gate.
- **The guard was inert.** An over-escaped pattern matched a literal backslash and never fired. It now catches write-capable secrets in upper *and* lower case.

Second commit is unrelated bookkeeping: the backlog index still advertised #85/#86 as open work while their own sections record them closed on 2026-08-20.
