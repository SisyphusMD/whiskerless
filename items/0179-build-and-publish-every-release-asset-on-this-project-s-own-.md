# #179 Build and publish every release asset on this project's own runners

- Kind: issue, state: closed, by cody, created 2026-11-16T18:35:40-08:00
- Labels: none; milestone: none

Every release asset is still built or tested on GitHub-hosted runners: the signed `.pkg`, the Homebrew bottles, the arm64 Linux set and the macOS and arm64 install legs. This project now has its own macOS 15, newest-macOS and arm64 runners, so all of that can move in-house and GitHub only receives the release.

- `release-macos.yml` and `bottles.yml` move to `.forgejo/workflows/`. The `.pkg` is built, signed, notarized and stapled on the macOS 15 VM and tested again on the newest-macOS VM. Bottles are built for macOS 15, Linux amd64 and Linux arm64. Each workflow uploads to all three releases (public Forgejo, NAS, GitHub).
- `release-arm64.yml` becomes the arm64 publisher. Its compare-with-GitHub shadow goes, and so does `.github/workflows/release-linux-arm64.yml`.
- `install-matrix.yml` covers Linux amd64, Linux arm64 and macOS in one run. `install-matrix-arm64.yml` and the GitHub install matrix go, along with `publish.yml`'s GitHub dispatch.
- The NAS bridge jobs (`nas-bridge`, `nas-bottles`) go, because every producer reaches the NAS directly. `reconcile` waits for the `.pkg` and the arm64 set before healing.
- The Apple signing secrets move to Forgejo org secrets.

Follows the CI-side change in #178.
