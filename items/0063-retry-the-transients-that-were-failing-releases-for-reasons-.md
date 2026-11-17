# #63 Retry the transients that were failing releases for reasons outside the repo

- Kind: pull, state: closed, by cody, created 2026-08-27T13:57:33-07:00
- Labels: none; milestone: none
- refs/pull/63/head -> main, merged: True

The rc.34 mirrorlist failure had no retry while its apt equivalent did. Adds a real retry to every network-backed package-manager call and to the CPython source fetch, using the retry helper this repo already had rather than a second one, and leaves the lifecycle assertions single-shot so a first-run failure cannot be retried into green. Also retries a registry transfer that resets mid-flight, verifying the stored bytes before reporting either success or failure.
