# #39 Warm the bottle mirror daily

- Kind: pull, state: closed, by cody, created 2026-08-24T15:46:29-07:00
- Labels: none; milestone: none
- refs/pull/39/head -> main, merged: True

The mirror syncs **on demand**, so the first request for a bottle it has never seen blocks while it pulls from ghcr.io — measured at about 21s per entry from a runner, against the roughly 7s Homebrew's default three retries allow. The smoke jobs raise that budget so a cold entry survives, but it is paid again on every dependency whenever upstream rebuilds its bottles.

This walks the formula's own dependency closure with `brew deps` and fetches each bottle with `brew fetch`, which is what populates the mirror. Nothing hardcodes a formula list that could drift from what the smoke installs.

**Verified on a real runner, not asserted:** whiskerless warms 62/62 of its closure and dreame 85/85, both with zero misses.

Three things a cold review caught, each fixed and then re-tested:

- `HOMEBREW_ARTIFACT_DOMAIN_NO_FALLBACK` is set **here only**. Without it every fetch could succeed from ghcr.io and report a warm mirror that received nothing. The smoke jobs deliberately keep the fallback, where a miss should cost latency rather than a red build.
- The **rc** formula is warmed first, and chosen by which file exists rather than by an exit code. `update-tap.sh` advances only the rc on a prerelease, so the stable formula lags — measured three dependencies short of its own rc in dreame.
- `brew trust` is applied as the install smoke does; without it, reading a third-party formula exits non-zero even when it printed the formula correctly, which silently selected the stale closure.

**Known limit, stated in the workflow:** the closure comes from the published tap, so a dependency newly added to the local formula template is not warm until a release publishes it. The first job to want it pays one cold sync, which the raised retry budget already absorbs.
