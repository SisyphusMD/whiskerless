# #181 ci: build and publish every release asset in-house (the .pkg, bottles, arm64 set and install legs no longer need GitHub-hosted runners)

- Kind: pull, state: closed, by cody, created 2026-11-16T21:31:46-08:00
- Labels: none; milestone: none
- refs/pull/181/head -> main, merged: True

Closes #179

Large diff: moving four release workflows from `.github` to `.forgejo` (or merging them in), plus the tests and docs that pin them, can't be split without leaving a release path half on GitHub.

## What changes
- `release-macos.yml` and `bottles.yml` move to Forgejo. The `.pkg` is built, signed, notarized and stapled on macos-15-vm, then tested on macos-27-vm. Bottles build on ubuntu-latest, ubuntu-26.04-arm and macos-15-vm. Each uploads straight to the Forgejo, NAS and GitHub releases. The nas-pkg and nas-bottles bridges are gone.
- `release-arm64.yml` is now the real arm64 publisher. `release-linux-arm64.yml`, the shadow and `compare-arch-build.sh` are deleted.
- One `install-matrix.yml` covers amd64, arm64 and both macOS VMs (pkg/spctl, bottle pour, uvx). The GitHub install matrix, `install-matrix-arm64.yml` and the GitHub dispatch are deleted.
- reconcile waits until the .pkg and arm64 set are on both the public Forgejo and the NAS.
- The stable-cut refusal step and its test are removed. `.github/workflows` is empty, and a test keeps it that way.
- Deviation, already approved: the .pkg and bottles stay as their own workflows instead of being folded into publish.yml.
- All eight `MACOS_*` secrets are present as Forgejo org secrets.

## Proof (private proof repo; build and verify only, no uploads)
- Bottles: all three legs. Keg lists and tabs are identical to the GitHub-built bottles (tab differences are only Homebrew version drift).
- Unsigned .pkg: payload files and per-binary minimum macOS are identical to the GitHub-built .pkg.
- macOS install legs on macos-15-vm and macos-27-vm: spctl accepts the published pkg as notarized, the bottle pours and uvx works, on two runs back to back.
- Signed .pkg, run 37953 (2 jobs): built, signed, notarized (Accepted) and stapled on macos-15-vm twice in a row. `stapler validate` OK, `spctl -a -t install` accepted as Notarized Developer ID, payload files IDENTICAL to the GitHub-built pkg (5 entries), and minimum macOS per binary IDENTICAL.

- Signing needed one change on the runner side: each job now sets the keychain search list and default (`list-keychains -d user -s`, `default-keychain -d user -s`), since every job starts with neither. A test pins both lines.

## Checks
ruff, mypy, pytest with coverage floors, shellcheck, actionlint and doc links all pass locally. Codex review found nothing.
