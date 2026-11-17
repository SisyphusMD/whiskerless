# #36 Remove `diagnose` and the false hold instruction (backlog #83, #84)

- Kind: pull, state: closed, by cody, created 2026-08-24T13:25:30-07:00
- Labels: none; milestone: none
- refs/pull/36/head -> main, merged: True

Closes the two pre-release text cleanups.

**#83** — `diagnose` is removed: the subcommand, its parser registration, the man-page entry, the README section and the `[Unreleased]` CHANGELOG bullet. `wifi_diagnosis`, `diagnose_wifi` and the `_describe_status` helper go with it; the entry warned that leaving `wifi_diagnosis` without a caller would be worse than deleting it.

**#84** — the timed pairing-window model is gone. The entry named six places; searching for the model rather than the sentence found seventeen more across twelve files. The phrase "pairing window" is retired from `src/`, `tests/`, `docs/` and the README, because it carries the expiry claim even where the surrounding sentence does not. `scan()` keeps its first-answer behaviour with no rationale attached, as the entry asked, and the capture notebook keeps what the bench session observed while marking the superseded reading.

Neither item has a dreame-valetudo equivalent: that repo has a `diagnose`, but it inspects a rooted robot over fastboot/UART.
