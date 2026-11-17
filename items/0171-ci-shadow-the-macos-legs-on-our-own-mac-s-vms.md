# #171 ci: shadow the macOS legs on our own Mac's VMs

- Kind: pull, state: closed, by cody, created 2026-11-16T11:10:03-08:00
- Labels: none; milestone: none
- refs/pull/171/head -> main, merged: True

Shadow of GitHub's `ci-macos.yml` and `formula-macos.yml` on our own Mac: macOS 15 (the floor) and the newest macOS, each in its own VM. Nothing GitHub does changes.

- `macos.yml` runs on every push to every branch, keyed per commit like GitHub's (cancelled only on Renovate branches), with the same `macos-scope.sh` skip for Linux-only Renovate branches. No pull_request trigger, so a fork's code never runs on these machines.
- The Homebrew formula smoke runs first, while the VM is as clean as a user's Mac, then the native tests, shellcheck and the release-script tests.
- Every check is continue-on-error; the verdict is the `SHADOW-VERDICT tier=... ci=... formula=...` line. The one step allowed to fail the job is the Python setup, so nothing pip-installs into the image's own interpreter.
- setup-python's macOS build expects GitHub's tool cache path and an admin runner user; the job provides the path and hands the framework it installs to the job user between the two attempts.

On this branch both VMs ran green: SHADOW-VERDICT ci=success formula=success on floor and current.

The switch (GitHub's copies go, the gates read this) is a later PR after about a week of agreement.
