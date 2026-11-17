# #59 Clear the leftovers: one ruff ruleset, one Windows position, nothing built twice

- Kind: pull, state: closed, by cody, created 2026-08-27T08:02:21-07:00
- Labels: none; milestone: none
- refs/pull/59/head -> main, merged: True

Converges the ruff ruleset and lint scope between the two projects and fixes everything the shared rules found, stops the Homebrew formula rebuilding what Homebrew already ships, and pins the README promises that nothing was checking: the macOS lanes, the shared Windows position, and the glibc floor the build actually enforces.
