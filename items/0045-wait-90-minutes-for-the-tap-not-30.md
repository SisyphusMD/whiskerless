# #45 Wait 90 minutes for the tap, not 30

- Kind: pull, state: closed, by cody, created 2026-08-25T11:28:15-07:00
- Labels: none; milestone: none
- refs/pull/45/head -> main, merged: True

`v0.3.0-rc.27` lost its bottles, and the install matrix that waits on them, to a **sixty-second** miss.

`build-bottles.sh` waits for publish.yml's first tap pass; publish.yml's second pass then waits for the bottles built here. That handshake is correct and unchanged. What failed was the budget: `90 x 20s` = **30 minutes**, against a publish that took **37m18s** to write the formula (started 16:45:56Z, tap pass landed 17:23:12Z). The loop gave up at 17:22:12Z. The formula appeared one minute later.

The same publish has reached the tap inside 17 minutes on other runs, so the spread is wide and 30 minutes sat inside it. Now `270 x 20s` = 90 minutes.

**Widening is close to free.** The loop breaks the moment the formula appears, so the budget is a FAILURE bound rather than a delay: it costs nothing on a healthy release and a longer red run when publishing is genuinely broken.

**This applies to stable too.** `bottles.yml` triggers on `v*.*.*`, so `v0.3.0` races exactly as the rc did — and stable's publish does more before the tap pass, while a stable tag is permanent. `retry-infra-failures` would not have saved it either: it re-runs *infrastructure* failures, and `::error::the tap never published…` is an application-level failure it correctly declines.

A new invariant fails if the budget drops under 60 minutes, mutation-tested against both factors — fewer iterations and a shorter sleep. The failure message now names the recovery dispatch.
