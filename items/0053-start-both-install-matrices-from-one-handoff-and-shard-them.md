# #53 Start both install matrices from one handoff, and shard them

- Kind: pull, state: closed, by cody, created 2026-08-26T13:58:26-07:00
- Labels: none; milestone: none
- refs/pull/53/head -> main, merged: True

The install matrix was the tail of every release. Two changes, measured rather than guessed.

**Both halves now start the same way.** The GitHub matrix triggered on the tag push — the same instant publish starts — and spent ~22 minutes waiting for artifacts that did not exist yet. Unlike the Forgejo case this starved nothing (its runners were free, and every leg started within seconds of the artifacts landing), so it buys no wall clock. It is for consistency: one mechanism starts both halves, and a mechanism that differs per forge is how the two drift apart. `publish.yml` now dispatches both.

**Both Linux legs are sharded.** The channels are independent and were only sequential by default. Measured on a real dispatch against v0.2.0-rc.51: the arm64 leg went from **33 minutes to 7m24s**, four shards balanced at 4m54s / 5m40s / 5m00s / 7m24s. The whole GitHub matrix dropped from 33 to 20 minutes; what remains is macOS **Intel** runners queueing ~15 minutes for capacity, which no workflow change reaches.

Shard counts differ per forge on purpose, the same way `CACHE_CEILING_GB` already does: GitHub gets four, Forgejo gets **two**, because that pool is exactly four self-hosted runners. Four shards there would take all of them — blocking the sibling project’s publish and every PR check — to speed up a leg measured at 8–14 minutes against GitHub’s 20+, which is not the critical path and so would not move the release at all.

An invariant pins the declared shard list against the count handed to the script. Passing four while declaring two would leave half the channels unselected, the shards that ran passing, and the architecture reported green having installed half of what it publishes.

**Note for whoever merges:** the GitHub dispatch needs `Actions: read & write` on `GH_REPO_WRITE_PAT`, which previously held Contents only. The requirement is now documented in `packaging/README.md`. If it is missing the handoff fails loudly within a second rather than silently skipping, and the matrix stays dispatchable by hand with a tag input.
