# Packaging & release

`launcher.py` is the PyInstaller entry point; `entitlements.plist` carries the
hardened-runtime exceptions PyInstaller needs for notarization; `nfpm.yaml` is
the `.deb`/`.rpm` recipe; `homebrew/` and `homebrew-cask.sh` are the Homebrew
cask and its regenerator; `changelog-section.sh`, `forgejo-release.sh`, and
`github-release.sh` are release helpers.

## How a release flows

Only `forgejo.bryantserver.com` can reach everything (itself, the **internal**
NAS, GitHub, PyPI); GitHub can't reach the NAS. So the public Forgejo orchestrates
and bridges.

1. **Cut it on Forgejo** — run the **Release** workflow (`.forgejo/workflows/release.yml`)
   from the Forgejo UI and pick `patch` / `minor` / `major`. (First release on a
   fresh repo: dispatch `minor` → `0.1.0`.) It advances the CHANGELOG, bumps every
   version string, runs the test gate, commits, tags, and pushes. Git push-mirror
   fans the commit + tag out to GitHub and the NAS Forgejo.
2. **Forgejo `publish.yml`** (tag-triggered): publishes the library to **PyPI**,
   builds the **Linux binary**, and **creates the release on all three** (Forgejo,
   NAS, GitHub) with the CHANGELOG section as the notes + the Linux binary.
3. **GitHub `release-macos.yml`** (mirrored tag, GitHub's free macOS runners — the
   one job that needs a Mac): builds the **signed + notarized `.pkg`** and appends
   it to the **GitHub** and **public-Forgejo** releases (all it can reach).
4. **GitHub `release-linux.yml`** (mirrored tag): builds the **arm64 Linux
   binary** on GitHub's native arm64 runner and the **`.deb` + `.rpm` for both
   architectures**, and appends them to the GitHub and public-Forgejo releases.
   The x86_64 raw binary is deliberately left to `publish.yml` so the two
   workflows never upload an asset of the same name.
5. **Forgejo `publish.yml` `nas-pkg` job**: waits for the `.pkg` on the public
   Forgejo release, then **copies it to the internal NAS** release.

All three releases end up with the same notes; PyPI has the library. The release
helpers are idempotent (create-or-reuse + replace assets), so the forges can
write the same release in any order.

### What each release carries

| Artifact | Built by | Runs on |
|---|---|---|
| `whiskerless` on PyPI | `publish.yml` | any Python 3.11+ |
| `whiskerless-linux-x86_64` | `publish.yml` | Linux, no Python needed |
| `whiskerless-linux-arm64` | `release-linux.yml` | Linux arm64 (Pi, arm servers) |
| `whiskerless_<v>_{amd64,arm64}.deb` | `release-linux.yml` | Debian / Ubuntu |
| `whiskerless-<v>.{x86_64,aarch64}.rpm` | `release-linux.yml` | Fedora / RHEL |
| `whiskerless-macos-{arm64,x86_64}.pkg` | `release-macos.yml` | macOS, signed + notarized |

The `.deb`/`.rpm` declare **no** dependency on a system Python: PyInstaller
bundles the interpreter, so the package works on a machine that has none. That
is the point — the audience is someone provisioning a robot from a laptop.

### Homebrew

`packaging/homebrew/whiskerless.rb` and `whiskerless-rc.rb` are **formulas**, not casks — a source
install into a virtualenv, matching how `dreame-valetudo` does it in the same tap. That needs no
Apple notarization (which applies only to the separate `.pkg`) and covers macOS and Linux on both
architectures from one file. The `-rc` formula is separate so a candidate can be validated through
the real Homebrew path without the stable formula ever pointing at one.

`publish.yml`'s `homebrew-tap` job renders them per tag via `update-tap.sh` and pushes to
`SisyphusMD/homebrew-tap`. A prerelease tag writes only `whiskerless-rc`; a stable tag writes both,
re-pointing the rc formula at the stable release so that channel keeps resolving once its candidates
are pruned.

**The checksum never comes from a download.** `update-tap.sh` builds the sdist locally from the
checked-out tag, hashes that, then requires PyPI to be serving identical bytes — a registry download
is exactly what the formula checksum is meant to protect users from. Verified reproducible here:
building from the `v0.1.3` tag reproduces the sha256 PyPI serves for 0.1.3, byte for byte. If that
stops holding, the job fails rather than publishing.

**Resources are generated, never hand-written.** `virtualenv_install_with_resources` installs each
resource with pip's `--no-deps`, so the list must be the complete closure; a partial one installs
cleanly and fails on the first import. bleak's dependencies differ by platform (pyobjc on macOS,
dbus-fast on Linux), emitted as `on_macos` / `on_linux` blocks. After any dependency change,
regenerate and paste between the RESOURCES markers in both formulas:

```bash
packaging/homebrew-resources.py
```

Needs `CLUSTER_FORGEJO_TAP_WRITE_PAT`.

## Transient runner failures

GitHub's hosted runners sometimes fail before any of our steps run — observed 2026-08-11, a
`Set up job` phase that could not parse `actions/checkout`'s own manifest on the macos-26 beta
image, while the same pinned SHA loaded fine on three other runners in the same matrix.

`retry-infra-failures.yml` handles those without a human, and deliberately handles nothing else:

- It re-runs **only** when every failed step is a phase the runner owns before ours begin
  (`Set up job` / `Set up runner`). A failing test always fails one of our named steps, so it can
  never be laundered into a green build here. `Complete job` is excluded on purpose: it fails after
  artifacts are uploaded, and artifacts are immutable within a run, so a retry could not succeed.
- It retries **once** (`run_attempt == 1`). A fault that recurs is not transient and stays red.
- Every invocation is the flake record: how often this workflow appears in the Actions tab is the
  number to watch. A cluster means a runner image regressed, not that we got unlucky.

## Secrets

### On Forgejo (`forgejo.bryantserver.com/SisyphusMD/whiskerless` → Settings → Actions → Secrets)

| Secret | What it is |
|---|---|
| `CLUSTER_FORGEJO_REPO_WRITE_PAT` | Forgejo PAT, repo write (push the release commit/tag + create/append the Forgejo release). You already use this on `archiver`. |
| `NAS_FORGEJO_REPO_WRITE_PAT` | PAT on the NAS Forgejo, repo write (create the NAS release + receive the bridged `.pkg`). |
| `GH_REPO_WRITE_PAT` | GitHub PAT, Contents: read & write (Forgejo creates the GitHub release with it). Same PAT used as the GitHub push-mirror password. |
| `PYPI_API_TOKEN` | PyPI API token (`pypi-…`). OIDC trusted publishing isn't available on Forgejo, so this is a token. Scope it to the project once it exists. |
| `CLUSTER_FORGEJO_TAP_WRITE_PAT` | Forgejo PAT with write access to `SisyphusMD/homebrew-tap`, so the `homebrew-tap` job can push the rendered formulas. |

### On GitHub (`github.com/SisyphusMD/whiskerless` → Settings → Secrets and variables → Actions)

| Secret | What it is |
|---|---|
| `CLUSTER_FORGEJO_REPO_WRITE_PAT` | same Forgejo write PAT (the macOS job appends the `.pkg` to the public Forgejo release). **The NAS PAT is *not* needed here — GitHub can't reach the NAS.** |
| `MACOS_APP_CERT_P12` | base64 of your **Developer ID Application** cert (`.p12`) |
| `MACOS_INSTALLER_CERT_P12` | base64 of your **Developer ID Installer** cert (`.p12`) |
| `MACOS_CERT_PASSWORD` | the `.p12` export password |
| `MACOS_APP_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `MACOS_INSTALLER_IDENTITY` | e.g. `Developer ID Installer: Your Name (TEAMID)` |
| `MACOS_NOTARY_KEY_P8` | base64 of your App Store Connect API key (`.p8`) |
| `MACOS_NOTARY_KEY_ID` | the API key's Key ID |
| `MACOS_NOTARY_ISSUER` | the API key's Issuer ID (a UUID) |

(`GITHUB_TOKEN` for the GitHub release is provided automatically.)

### Getting the macOS bits (one-time, Apple Developer Program)

1. **Certificates** — in Keychain Access, *Certificate Assistant → Request a
   Certificate from a CA*. At <https://developer.apple.com/account/resources/certificates>
   create a **Developer ID Application** and a **Developer ID Installer**
   certificate from that CSR, install them, then export each (with its private key)
   as a `.p12` with a password and base64 it: `base64 -i cert.p12 | pbcopy`.
2. **Notary key** — at <https://appstoreconnect.apple.com/access/integrations/api>
   create a key with **Developer** access. Download the `.p8` (offered once), note
   the **Key ID** and **Issuer ID**, base64 the `.p8`.
3. **Identities** — the exact common names from `security find-identity -v`;
   `TEAMID` is your 10-character Team ID.

If the macOS secrets are missing, only the macOS job fails — PyPI, the Linux
binary, and the Forgejo/NAS releases still complete.
