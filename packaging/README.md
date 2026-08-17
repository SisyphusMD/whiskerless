# Packaging & release

`launcher.py` is the PyInstaller entry point; `entitlements.plist` carries the
hardened-runtime exceptions PyInstaller needs for notarization; `nfpm.yaml` is
the `.deb`/`.rpm` recipe; `homebrew/` holds the Homebrew formulas, regenerated
by `update-tap.sh` + `homebrew-resources.py`; `changelog-section.sh`,
`forgejo-release.sh`, and `github-release.sh` are release helpers.

## Release asset naming

Names this project chooses use `x86_64` / `arm64` (Apple's own vocabulary, and
what `uname -m` prints on the machines people download from most) and carry the
version, so a file in someone's Downloads identifies its release:

    whiskerless-<version>-linux-<arch>        raw Linux binary
    whiskerless-<version>-macos-<arch>.pkg    signed macOS installer
    whiskerless_<version>_<arch>.deb          Debian package  (mandated form: amd64/arm64)
    whiskerless-<version>.<arch>.rpm          RPM package     (mandated form: x86_64/aarch64)

The `.deb`/`.rpm` names are their ecosystems' mandated forms — do not "unify"
them, tooling parses them. Prereleases use `~rc.N` **inside the packages** (deb
and rpm both sort `~` before the release, which a prerelease must, and a bare
`-rc.N` is illegal in a deb version) and `-rc.N` everywhere else. Known and
accepted: GitHub's asset API rewrites `~` to `.` in the uploaded FILENAME only
(`whiskerless_0.2.0~rc.6_amd64.deb` appears there as
`whiskerless_0.2.0.rc.6_amd64.deb`); the packages' internal versions — what
`dpkg`/`dnf` order by — are unaffected, and Forgejo serves the canonical names.
New artifacts follow this scheme rather than inventing another spelling.

## How a release flows

Only `forgejo.bryantserver.com` can reach everything (itself, the **internal**
NAS, GitHub, PyPI); GitHub can't reach the NAS. So the public Forgejo orchestrates
and bridges.

0. **The mirror gates the cut.** Forgejo has no macOS runner, so nothing here can
   build the Homebrew formula on a Mac — and that build is the one that broke
   silently for a whole release candidate (`cryptography`'s Rust extension,
   stripped by cargo into a Mach-O dyld refuses; the Linux smoke passed
   throughout). `mirror-gate` therefore blocks `tag` until **`Homebrew formula (macOS)` is
   green on GitHub for the commit the release is cut from** — see
   `packaging/check-mirror-ci.sh`. Note "cut from", not "tagged": the tag job
   stamps version strings and commits, so the tagged tree is a *child* of the
   gated SHA, and for a prerelease that child is never pushed to a branch at all,
   so no branch workflow could ever evaluate it. Gating the parent is sound
   because the tag job's own intent check already refuses unless the diff is
   exactly the version-stamped files — none of which is the formula, or any code
   the formula compiles. The job holds **no write credential** by design — that is
   the property that matters, since it cannot push anything — and the mirror is
   public, so it needs no credential at all to read.

   The check it waits on lives in its **own** workflow
   (`.github/workflows/formula-macos.yml`), keyed per commit with
   `cancel-in-progress: false`, rather than alongside the macOS test matrix.
   That is load-bearing: `ci-macos.yml` cancels superseded runs, which is right
   for a fast matrix and wrong here — a cancelled run reads as not-green, so any
   push landing during a release cut used to kill the very run the release was
   waiting on. Split out, each commit's verdict stands on its own and survives
   whatever lands after it, so pushing during a release is safe again.

   **Add `GH_REPO_READ_PAT` if the gate starts timing out.** Unauthenticated GitHub
   allows 60 API requests an hour *per IP*, shared with everything else leaving
   this network — exhaust it and the gate polls uselessly and then fails a
   release that was never broken (seen 2026-08-17). A token with **no scopes at
   all** lifts that to 5,000/hour on a public repo. It is optional: absent, the
   gate still works, just slowly, and it distinguishes "rate-limited" from "not
   green" in its failure message so nobody debugs the wrong thing.

   It **waits** rather than failing
   fast, because the push-mirror is asynchronous — a release dispatched moments
   after a push finds no run at all for a while. A `cancelled` run counts as
   not-green, which matters: pushing again cancels the previous run.

1. **Cut it on Forgejo** — run the **Release** workflow (`.forgejo/workflows/release.yml`)
   from the Forgejo UI and pick `patch` / `minor` / `major`. (First release on a
   fresh repo: dispatch `minor` → `0.1.0`.) It advances the CHANGELOG, bumps every
   version string, runs the test gate, commits, tags, and pushes. Git push-mirror
   fans the commit + tag out to GitHub and the NAS Forgejo.
2. **Forgejo `publish.yml`** (tag-triggered): publishes the library to **PyPI**,
   builds **every Linux artifact** — raw binaries, `.deb` and `.rpm` for amd64 and
   arm64 — and **creates the release on all three** (Forgejo, NAS, GitHub) with the
   CHANGELOG section as the notes. Both architectures build locally: buildx's
   docker-container driver carries QEMU, so the arm64 leg emulates inside the
   builder rather than needing an arm64 runner.
3. **GitHub `release-macos.yml`** (mirrored tag, GitHub's free macOS runners — the
   one job that genuinely needs a Mac): builds the **signed + notarized `.pkg`** and
   appends it to the **GitHub** and **public-Forgejo** releases (all it can reach).
4. **Forgejo `publish.yml` `nas-pkg` job**: waits for the `.pkg` on the public
   Forgejo release, then **copies it to the internal NAS** release.

All three releases end up with the same notes; PyPI has the library. The release
helpers are idempotent (create-or-reuse + replace assets), so the forges can
write the same release in any order.

### What each release carries

| Artifact | Built by | Runs on |
|---|---|---|
| `whiskerless` on PyPI | `publish.yml` | any Python 3.11+ |
| `whiskerless-linux-x86_64` | `publish.yml` | Linux, no Python needed |
| `whiskerless-linux-arm64` | `publish.yml` | Linux arm64 (Pi, arm servers) |
| `whiskerless_<v>_{amd64,arm64}.deb` | `publish.yml` | Debian / Ubuntu |
| `whiskerless-<v>.{x86_64,aarch64}.rpm` | `publish.yml` | Fedora / RHEL |
| `whiskerless-macos-{arm64,x86_64}.pkg` | `release-macos.yml` | macOS, signed + notarized |
| `SHA256SUMS` | `publish.yml` | checksums for every Linux artifact |

Verify a download with **`sha256sum -c --ignore-missing SHA256SUMS`**. The
`--ignore-missing` is required, not optional: an artifact whose version contains
`~` is listed twice — once under the canonical name Forgejo serves, once under
the `.`-rewritten name GitHub's asset API produces — so whichever forge you
downloaded from, the other spelling is a line with no local file. Checksums prove
the bytes arrived intact; they are served from the same host as the artifacts, so
they say nothing about authenticity. That is what the GPG signature on the
packages is for.

The `.deb`/`.rpm` declare **no** dependency on a system Python: PyInstaller
bundles the interpreter, so the package works on a machine that has none. That
is the point — the audience is someone provisioning a robot from a laptop.

Both are **installed and run before they are published**, on both architectures,
by `publish.yml`'s package smoke step. The smokes prove install-and-run; they can
no longer prove the glibc floor dynamically — since the build moved to a
manylinux_2_28 image, the build image *is* the floor, so no distro can sit
between them. The floor is enforced statically instead, by
`check-glibc-floor.py` scanning every ELF (outer and embedded) for its highest
`GLIBC_` requirement.

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
| `GH_REPO_READ_PAT` | **Optional.** GitHub PAT with **no scopes** — read-only public data, used solely by `mirror-gate` to escape the 60-request/hour unauthenticated limit. Absent, the gate still works and just polls slowly. |
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
