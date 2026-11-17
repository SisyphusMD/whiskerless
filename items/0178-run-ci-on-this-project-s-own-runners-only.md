# #178 Run CI on this project's own runners only

- Kind: issue, state: closed, by cody, created 2026-11-16T18:24:00-08:00
- Labels: none; milestone: none

No job in this project should run on GitHub-hosted runners any more. The macOS suites already run on this project's own Macs (`macos.yml`, macOS 15 and the newest macOS). The GitHub copies and the CI job that waited on them can go.

- `macos.yml` becomes the macOS gate. Its two jobs become required checks on `main`, replacing `CI / macos`, and the release workflows check it on the commit they cut from.
- Delete the GitHub CI workflows: `ci-pr.yml`, `ci-macos.yml`, `formula-macos.yml` and `retry-infra-failures.yml` and `hassfest.yml` (`ci.yml` already runs hassfest and HACS).
- Re-vendor the standard from the release that retires the GitHub-runner helpers.
- Update the docs and invariant tests that describe the GitHub side.

The release-side GitHub workflows (the `.pkg`, bottles, arm64 and install-matrix legs) move in a separate change.
