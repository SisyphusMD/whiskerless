# #170 ci: build and install-test arm64 on our own runner beside GitHub's (shadow)

- Kind: pull, state: closed, by cody, created 2026-11-16T10:44:25-08:00
- Labels: none; milestone: none
- refs/pull/170/head -> main, merged: True

Shadow of the two GitHub arm64 legs on our own native arm64 runner. Nothing GitHub does changes, and nothing here can fail a release or the stable gate.

- `release-arm64.yml` (tag push): builds the arm64 assets the way `release-linux-arm64.yml` does, publishes nothing, and compares them with the copies GitHub appends (`packaging/compare-arch-build.sh`: package metadata, file lists with modes and link targets, signatures, archive contents).
- `install-matrix-arm64.yml` (dispatched by `publish.yml` beside the other two matrices): the same four arm64 install shards.
- Both are their own workflows so a queued or slow arm64 job can never hold the publish run or the install-matrix run the stable gate reads. Every step that can fail is continue-on-error; the verdict is the `SHADOW-VERDICT` line.

Proved on a throwaway repo against the current candidates (dreame-valetudo v0.3.0-rc.49, whiskerless v0.2.0-rc.76): both builds `VERDICT agree` with GitHub's assets; install shards all pass except dreame-valetudo's bottle-pour, because the tap carries no bottle for rc.49 (GitHub's own rc.49 matrix never reached its shards: its wait found the macOS .pkg missing).

The flip (the upload replaces the compare, GitHub's copies go) is a later PR once a real release candidate shows both agree.
