# #40 Build the formula on every macOS lane the library is tested on

- Kind: pull, state: closed, by cody, created 2026-08-24T16:38:13-07:00
- Labels: none; milestone: none
- refs/pull/40/head -> main, merged: True

The formula job proved current arm64 and nothing else, while `ci-macos.yml` holds the library to four lanes. Both formulae compile native code on the installing machine — a Rust extension in whiskerless, `sunxi-tools` built with `make sunxi-fel` here — so a break can be specific to Intel or to the macOS floor. The bottle build does cover those lanes, but only at tag time, and a tag is immutable by the time it reports.

Four lanes of a job that compiles is not cheap. Killing this workflow's duplicate `pull_request` run earlier paid for half of it; the rest buys the only coverage that was missing.

A new invariant fails if the two lane sets ever diverge again, in either direction.
