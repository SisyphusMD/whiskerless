# #58 Stop paying for work already done, and check what the matrix actually installs from

- Kind: pull, state: closed, by cody, created 2026-08-26T21:46:18-07:00
- Labels: none; milestone: none
- refs/pull/58/head -> main, merged: True

Takes cryptography from Homebrew instead of building its Rust sdist, frees tap pass 1 and the install-matrix handoff from edges they read nothing from, and makes release readiness cover the GitHub release the matrix actually downloads from.
