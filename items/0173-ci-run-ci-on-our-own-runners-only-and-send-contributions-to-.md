# #173 ci: run CI on our own runners only, and send contributions to Forgejo

- Kind: pull, state: closed, by cody, created 2026-11-16T12:13:02-08:00
- Labels: none; milestone: none
- refs/pull/173/head -> main, merged: True

Closes #178

Large diff: mostly deletions. The GitHub CI workflows go, the vendored helpers that bridged to them are replaced by the project-rules v0.3.0 re-vendor, and their invariant tests go with them.

**Contributing.** Issues and pull requests go to Forgejo, where anyone can sign in with a GitHub account; the GitHub repository is a read-only mirror. CONTRIBUTING describes the AGit flow (`git push origin HEAD:refs/for/main -o topic=…`). CI does not run on a pull request sent that way: the runners are trusted with release credentials. A maintainer reads the change and opens it again from a branch here, which runs the whole suite.

**CI on our own runners only.**
- `macos.yml` is the macOS gate, on macOS 15 and the newest macOS. It runs on push to every branch, never on pull_request, and swallows no failures (only the setup-python fallback stays tolerated).
- Its two jobs replace `CI / macos (pull_request)` as required checks on `main`: `macOS / macOS floor (macos-15-vm) (push)` and `macOS / macOS current (macos-27-vm) (push)`. Branch protection is updated when this merges.
- `ci.yml` loses the `macos` job that waited on GitHub's run.
- The release and prerelease `mirror-gate` becomes `macos-gate`. It runs `check-forgejo-ci.sh <sha> macos.yml` with no credential, and passes only a run whose every job succeeded, so a scoped-out Renovate run cannot qualify a cut.
- The candidate gate asks Forgejo only. It reads `install-matrix.yml` (amd64) and refuses to trust a shadow matrix: `install-matrix-arm64.yml` swallows its own failures, so a test now fails if it is ever listed in `INSTALL_MATRIX_WORKFLOWS`.
- Deleted: `.github/workflows/ci-pr.yml`, `ci-macos.yml`, `formula-macos.yml` and `retry-infra-failures.yml` and `hassfest.yml` (`ci.yml` already runs hassfest and HACS from their images). With them go the vendored `check-mirror-ci.sh`, `triage-infra-failure.py`, `forgejo-preflight.sh` and their tests.
- Docs (`docs/design/ci-split.md`, `packaging/README.md`) and invariant tests are rewritten to match. The new tests check that `macos.yml` never runs on pull_request, swallows nothing and covers both macOS legs. They also check that the release gate requires a fully green run on the exact commit, and that the candidate gate lists every install-matrix workflow.

**Release side, until the release-in-house PR lands.**
- The re-vendor removes `forgejo-preflight.sh`, so this PR deletes its step from the GitHub release workflows that remain. Its only reader was the infra-retry workflow, which goes too.
- The candidate gate now reads Forgejo only and cannot see GitHub's macOS and arm64 install legs. So `release.yml` refuses a stable cut while `.github/workflows/install-matrix.yml` exists; a test pins that refusal. Prereleases are unaffected.
- The release-in-house PR moves those legs here and removes both the file and the refusal.

**Also tightened.**
- The AGit trust-gate test covers every job of a pull-request workflow, with recorded exceptions, not only the jobs that already had a head-repository check.
- The ref check on the gated macOS workflow is case-insensitive, so a script reading `$GITHUB_REF` is caught too.

Checks run here: ruff, mypy, the full pytest suite, `tests/release/*.sh`, `shellcheck-all.sh`. cx review raised the release-side gaps above (fixed by the preflight removal and the refusal); qx reviewed the follow-ups.
