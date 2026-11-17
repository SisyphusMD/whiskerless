# #83 fix(release): replay the tap push when the sibling lands between clone and push

- Kind: pull, state: closed, by cody, created 2026-08-29T15:31:05-07:00
- Labels: none; milestone: none
- refs/pull/83/head -> main, merged: True

Reproduced on v0.3.0-rc.44: its tap job failed `! [rejected] main -> main (fetch first)` because whiskerless rc.65 wrote the shared tap first.

The hazard was already documented at the job - "three jobs write this one repository, and two of them cloning the same tip means the loser pushes a non-fast-forward" - and the mitigation was `concurrency: group: tap-write`. But a concurrency group is scoped to one repository, so it cannot serialise the SIBLING, and both projects publish into `SisyphusMD/homebrew-tap`.

All six writer sites across the two repos (publish.yml pass 1 and pass 2, tap-bottles.yml, in each) now fetch, rebase onto the new tip and retry. Each project renders only its own formula file, so replaying is the correct resolution; a conflict means a genuine collision and still fails loudly.
