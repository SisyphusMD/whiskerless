# #20 Converge the release pipeline: native arm64, no emulation, and the audit fixes

- Kind: pull, state: closed, by cody, created 2026-08-22T07:21:39-07:00
- Labels: none; milestone: none
- refs/pull/20/head -> main, merged: True

Converges the release pipeline with dreame-valetudo and removes every trace of QEMU emulation.

**Architecture decides the forge, and nothing is emulated.** amd64 builds and install-tests on the
Forgejo runner; arm64 and macOS on GitHub's native runners. `build-linux-arch.sh` and
`install-matrix-arch.sh` refuse to run when the host and target architectures disagree, so an
emulated build cannot come back by accident. This retires the PyInstaller 6.22.0 pin, whose only
cause was emulation, and deletes the watch script that tracked it.

**Release-path fixes found by a cold cross-repo audit:**

- the manual prune failed *open* on a malformed `dry_run`, and ran the dispatched branch's script
- the macOS signing workflow held eight secrets job-wide and never removed the decoded key files
- the `.pkg` was built on macOS 26 with no deployment target and published untested, while the
  README claims macOS 15
- the macOS toolchain was unpinned, so one release could freeze its `.pkg` and its Linux artifacts
  with different PyInstallers
- jobs carrying `always()`/`!cancelled()` ran even when the ref guard *refused* the ref, doing
  external writes with `GITHUB_REF_NAME` set to a branch name
- the repository index was matched on version alone — and the registry is owner-scoped, so
  dreame-valetudo's package at the same version could satisfy the check
- all five compat floors were unclamped and would have drifted into second current-release tests

Checksums are now per-architecture (`SHA256SUMS-$(uname -m)`), each written by the machine that
built those bytes. Users on apt/dnf, Homebrew, PyPI or macOS are unaffected — those verify
automatically and never touch this file.

**Do not cut a release from `main` until this lands:** both forges now sign with the namespace key
`CCE50015D058E9BF`, which only this branch publishes.
