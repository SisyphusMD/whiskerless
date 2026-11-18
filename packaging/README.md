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
    whiskerless-<version>-macos-arm64.pkg     signed macOS installer
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

## Homebrew formula pull requests

After PyPI publishes the source archive, the release workflow renders the formulae
without a write credential. A separate job opens a reviewed PR on the primary tap
and waits for the exact files on its main branch. Bottle builders wait for the
matching source formula before allocating native build runners. After bottle
manifests publish, the second tap PR adds the bottle checksums. Install and cleanup
jobs keep waiting until those exact formula files are available.

If tap review exceeds the wait budget, finish the PR and rerun the affected
publisher jobs. If the separate Bottles workflow timed out waiting for the
formula, dispatch it again with the same tag. Use Tap Bottles from main to
repair the declarations after rebuilding bottles for an existing tag.

## How a release flows

Every job runs on our own runners, which reach everything (both Forgejo
instances, including the **internal** NAS, GitHub and PyPI). GitHub only
receives the release.

0. **The macOS run gates the cut.** The release jobs never build the Homebrew
   formula on a Mac, and that build is the one that broke silently for a whole
   release candidate (`cryptography`'s Rust extension, stripped by cargo into a
   Mach-O dyld refuses; the Linux smoke passed throughout). `macos-gate`
   therefore blocks `tag` until **`macos.yml` is fully green for the commit the
   release is cut from**, on macOS 15 and the newest macOS — see
   `packaging/check-forgejo-ci.sh`. Note "cut from", not "tagged": the tag job
   stamps version strings and commits, so the tagged tree is a *child* of the
   gated SHA, and for a prerelease that child is never pushed to a branch at all,
   so no branch workflow could ever evaluate it. Gating the parent is sound
   because the tag job's own intent check already refuses unless the diff is
   exactly the version-stamped files — none of which is the formula, or any code
   the formula compiles. The job holds **no credential** by design: it cannot push
   anything, and the run status it reads is public.

   `macos.yml` is keyed per commit and never cancels a superseded run (except on
   a Renovate branch, whose commits are never released). That is load-bearing: a
   cancelled run reads as not-green, so a push landing during a release cut would
   otherwise kill the very run the release is waiting on.

   It **waits** rather than failing fast, because a release dispatched moments
   after a push can find the run still queued, or not created yet.

1. **Prepare and merge the release on Forgejo.** Run **Prepare Release** from `main`
   with a release issue number and choose `patch` / `minor` / `major`. The workflow promotes
   the changelog, checks the existing qualification gates, stamps the version files,
   and opens a release PR. Merge it while it is up to date with `main` and all checks
   are green. An update to the prepared head invalidates its qualification. If `main` moved, close the stale PR, retire its branch with approval,
   and run Prepare Release again for the same issue. If it already merged, revert
   the stale promotion through a PR before preparing again.

   Run **Publish Release** from `main` with the merged PR number. The workflow tags
   that exact commit and starts the existing artifact publishers. The changelog lists the
   latest bump per dependency since the previous release.
2. **Forgejo `publish.yml`** (tag-triggered): publishes the library to **PyPI**,
   builds the **amd64 Linux artifacts** — raw binary, `.deb`, `.rpm` — and
   **creates the release on all three** (Forgejo, NAS, GitHub) with the CHANGELOG
   section as the notes. amd64 only, natively: architecture decides the forge here
   and nothing is emulated (`docs/design/ci-split.md`).
3. **`release-arm64.yml`** (the same tag, our native arm64 runner): the same
   build, for arm64, on real arm64 silicon. It **appends** its artifacts to all
   three releases step 2 created rather than making its own, so a failure here
   costs a release its arm64 half instead of blocking the whole thing. Both steps
   run `packaging/build-linux-arch.sh`, which refuses to run for an architecture
   its host is not.
4. **`release-macos.yml`** (the same tag, the macOS 15 VM): builds the **signed +
   notarized `.pkg`**, installs it again on the newest-macOS VM, and appends it to
   all three releases.
5. **`bottles.yml`** (the same tag): builds the three **Homebrew bottles** (macOS
   15, Linux amd64, Linux arm64) and appends them, with their manifests, to all
   three releases. Bottles stay out of reconcile's byte-quorum, which is a
   different question from mirroring (see `packaging/asset-roles.sh`).
6. **`publish.yml` bottle jobs**: `render-homebrew-bottles` waits for the
   manifests and renders the `bottle do` block. `homebrew-bottles` opens
   the second tap PR and waits for it to land.

All three releases end up with the same notes; PyPI has the library. The release
helpers are idempotent (create-or-reuse + replace assets), so the forges can
write the same release in any order.

### What each release carries

| Artifact | Built by | Runs on |
|---|---|---|
| `whiskerless` on PyPI | `publish.yml` | any Python 3.11+ |
| `whiskerless-linux-x86_64` | `publish.yml` | Linux, no Python needed |
| `whiskerless-linux-arm64` | `release-arm64.yml` | Linux arm64 (Pi, arm servers) |
| `whiskerless_<v>_amd64.deb` | `publish.yml` | Debian / Ubuntu |
| `whiskerless_<v>_arm64.deb` | `release-arm64.yml` | Debian / Ubuntu on arm |
| `whiskerless-<v>.x86_64.rpm` | `publish.yml` | Fedora / RHEL |
| `whiskerless-<v>.aarch64.rpm` | `release-arm64.yml` | Fedora / RHEL on arm |
| `whiskerless-macos-arm64.pkg` | `release-macos.yml` | macOS, signed + notarized |
| `whiskerless{,-rc}-<v>.<platform>.bottle.tar.gz` | `bottles.yml` | Homebrew, poured not compiled |
| `SHA256SUMS-x86_64` | `publish.yml` | checksums for the amd64 Linux artifacts |
| `SHA256SUMS-aarch64` | `release-arm64.yml` | checksums for the arm64 Linux artifacts |

Architecture picks the runner, and nothing is emulated: amd64 builds on the
cluster runner, arm64 on the native arm64 runner, macOS on the macOS 15 VM. That
split is why there are two checksum files — each is written by the machine that
built those bytes, and published assets are immutable, so the amd64 file cannot
be reopened when the arm64 job lands.

The `.deb`/`.rpm` are **also pushed into the apt/dnf repositories** (below), which
is how most people should install them. Neither checksum file covers the `.pkg` or
the bottles; both carry a stronger guarantee of their own anyway (notarization; a
sha256 inside the formula).

Verify a download with **`sha256sum -c --ignore-missing SHA256SUMS-$(uname -m)`**.
The file is named for `uname -m` — `x86_64`, `aarch64` — rather than the artifacts'
own `amd64`/`arm64` spelling, so that command needs no editing on the machine doing
the verifying. The `--ignore-missing` is required, not optional: an artifact whose
version contains `~` is listed twice — once under the canonical name Forgejo serves,
once under the `.`-rewritten name GitHub's asset API produces — so whichever forge
you downloaded from, the other spelling is a line with no local file. Checksums
prove the bytes arrived intact; they are served from the same host as the artifacts,
so they say nothing about authenticity. That is what the GPG signature on the
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
Apple notarization (which applies only to the separate `.pkg`) and covers macOS on Apple Silicon and Linux on
amd64/arm64 from one file. The `-rc` formula is separate so a candidate can be validated through
the real Homebrew path without the stable formula ever pointing at one.

`publish.yml` renders them per tag via `update-tap.sh`. The `homebrew-tap` job opens the formula
PR on `SisyphusMD/homebrew-tap`. A prerelease tag updates only `whiskerless-rc`. A stable tag updates both,
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

### Bottles

Without a bottle, Homebrew builds every resource from source — and `cryptography`
is a Rust extension, so `brew install` pulls `rust` → `llvm` (~2.4 GB) and
compiles for minutes. A bottle is a prebuilt keg: ~7 MB, poured instantly. It
covers the *whole* formula, so it removes `cffi`'s and `pyobjc-core`'s C builds
too, and because `rust`/`pkgconf` are `=> :build`, a bottled user never installs
them at all.

**Three platforms**: `arm64_sequoia`, `x86_64_linux`, `arm64_linux`. No Intel macOS bottle: Intel Macs
are not supported. Not one per
macOS release — Homebrew pours an older bottle when
none matches, verified on a macOS 27 machine pouring `arm64_tahoe` (26) bottles.
So building the floor (macos-15) covers everything above it. Note macOS 16–25 do
not exist: Apple went 15 → 26 → 27, so those two are consecutive.

**A stable tag builds six, not three.** Bottle filenames embed the *formula*
name and the keg inside is rooted at `<formula>/<version>/`, so a `whiskerless`
bottle can be neither renamed nor relabelled into a `whiskerless-rc` one. Since a
stable tag re-points the rc formula at the stable release, that release has to
carry a full set under *both* names — otherwise `brew install whiskerless-rc`
finds a block naming files that were never built and silently falls back to
compiling.

**Two tap passes, and they cannot be merged.** A bottle is produced by installing
the published formula, so the formula must exist first; the block can only be
written once the bottles do. Pass one publishes the formula (`update-tap.sh <tag>
<tap>`), pass two adds the block (`update-tap.sh <tag> <tap> <manifest-dir>`).
The second accepts an equal version for exactly this reason, and refuses to write
a block that is not the complete set — a missing platform is otherwise invisible,
and its users just go back to compiling.

`root_url` points at the Forgejo release, so the bottles ride as release assets
and `prune-rcs` collects them with the release they belong to. Homebrew fetches
`<root_url>/<filename>`, where `filename` is the single-dash name in the manifest
— `brew bottle` writes a double-dash local name that must be renamed before
upload.

The Linux legs build inside the **pinned** `homebrew/brew` image rather than the
runner's own Homebrew: the Linux runners carry none, and that image is already
what the Linux formula smoke proves the formula in.

## apt / dnf repositories

`publish.yml` pushes every `.deb` and `.rpm` into **Forgejo's native Debian and
RPM registries**, so the normal install is `apt install whiskerless` rather than
downloading a file. Endpoints (Forgejo 16 — the two formats do not share a
shape, and neither is guessable from the other):

```
PUT /api/packages/SisyphusMD/debian/pool/{distribution}/{component}/upload
PUT /api/packages/SisyphusMD/rpm/{group}/upload
```

Public instance only: an `apt update` resolves this host on every run, and the
NAS is not reachable from outside the house. Needs
`CLUSTER_FORGEJO_REGISTRY_PUSH_PAT` — the org-level PAT the sister repos already
push container images with. Forgejo scopes packages separately, so the release
PAT's `write:repository` **cannot** upload one; `write:package` covers upload,
listing and delete across every package type.

**Two distributions, `stable` and `testing`.** Version ordering alone cannot keep
candidates away from release subscribers: `0.2.0~rc.28` sorts below `0.2.0`, which
only helps once `0.2.0` exists — until then the newest thing in the repository
*is* the candidate. So a candidate goes to `testing` only, and a release goes to
**both** — leaving it out of `testing` would strand testers on the last rc, and
pruning that rc would then take the package away from them entirely.

**Who signs what.** The two ecosystems authenticate different things, and that
asymmetry is theirs, not a choice made here:

- **apt authenticates the repository index**, which **Forgejo** signs with its own
  Debian key. It does not check the `_gpgorigin` member nfpm embeds — proven by
  installing our signed `.deb` with only Forgejo's key imported. So on the apt
  side our signature is inert, and Forgejo's key is unavoidable: there is no API
  to make the registry sign the index with a key of ours, and substituting one
  would mean hand-writing a private key into a plaintext database column.
- **dnf authenticates the package**, and that signature is **ours**
  (`CCE50015D058E9BF`). Forgejo stores and serves the uploaded bytes unmodified,
  so it survives intact.

Forgejo generates a **separate key per registry type**: `debian/repository.key`
and `rpm/repository.key` are different keys.

**Forgejo can sign RPMs itself** — `PUT …/rpm/{group}/upload?sign=true`, or the
`DEFAULT_RPM_SIGN_ENABLED` server setting (verified: the file grows, and `rpm -K`
then wants Forgejo's key). Deliberately not used. It would replace the anchor we
control with one living in plaintext on the machine that serves the packages, and
it would make the registry copy of a release differ from the identical-looking
file on the release page.

**`whiskerless-signing-key.asc` is kept, and must not be deleted.** It is a
byte-identical copy of `sisyphusmd-signing-key.asc`. Two 0.2.0 release candidates
shipped a `whiskerless.repo` naming that URL in `gpgkey=`, and a machine
configured from one of them reads its own copy under `/etc/yum.repos.d` — never
this repository's. Removing the key it points at would leave dnf unable to import
the key the packages are now signed with, so that machine could not upgrade at
all. A repo invariant pins the two files identical.

**The dnf config ships in this repository** (`sisyphusmd.repo`,
`sisyphusmd-testing.repo`) rather than pointing users at the one Forgejo
generates, and it lists **only our key**. Both halves matter, and both were
checked against the live registry:

| `gpgkey=` contains | a package signed only by Forgejo's key |
|---|---|
| ours + Forgejo's | **installs** |
| ours alone | `GPG check FAILED` |

dnf accepts a package signed by *any* key in `gpgkey`, so listing Forgejo's
"as well, to be safe" would make a compromise of that single host enough to
install arbitrary code on every subscriber.

**zypper cannot use the repository**, and that is why openSUSE is documented as a
single-file install. It verifies the repository index even with
`repo_gpgcheck=0` — checked, it fails with `Signature verification failed for
repomd.xml` — so the only way to satisfy it is to trust Forgejo's key, which puts
that key in the rpm keyring and lets a Forgejo-signed package pass `pkg_gpgcheck`
too. Same weakness as listing it under `gpgkey`, arrived at by a different route. `repo_gpgcheck` is therefore `0`: it
would check the index against a key stored on the very host it defends against,
which buys little and costs the property above. Nothing can be *installed*
without our key; the residual gap is that a compromised host could withhold an
update rather than forge one.

The one-time key import cannot be automated away — apt will not install a package
to obtain the key it needs to trust that package. A Chrome-style self-registering
`.deb` was considered and rejected.

### Pruning them

`prune-rcs.sh` sweeps the registry alongside the releases, on the same "only once
the stable exists on all three hosts" guard, and it also *enumerates* from the
registry — so a candidate whose release was already deleted by a half-finished
sweep is still found and removed.

**The two formats need opposite delete endpoints**, which is not a preference and
is invisible at the API — every call returns 204 either way:

| | rebuilds the index | leaves it stale |
|---|---|---|
| **debian** | generic `/api/v1/packages/{owner}/debian/{name}/{version}` | pool endpoint |
| **rpm** | native `/api/packages/{owner}/rpm/{group}/package/…` | generic endpoint |

Get it backwards and the file 404s while the published index keeps advertising
it, so a package manager offers a version it cannot download. Both directions
were checked against the live registry.

Versions are looked up, never constructed: debian reports `0.2.0~rc.28` while rpm
reports `0.2.0~rc.28-1`, and a constructed rpm version 404s every time. The sweep
also filters by package **name** — this owner holds the sister projects'
container images, and the delete is by version.

## Transient runner failures

Nothing retries an infra failure automatically. A job that dies before any of our steps run (a
runner fault, not a test) is rerun by hand from the Actions tab; one that recurs is not transient and
gets fixed at the runner. The GitHub-side retry workflow and its edge-ban preflight went with the
GitHub-hosted runners they existed for.

## Secrets

### On Forgejo (`forgejo.bryantserver.com/SisyphusMD/whiskerless` → Settings → Actions → Secrets)

| Secret | What it is |
|---|---|
| `CLUSTER_FORGEJO_REPO_WRITE_PAT` | Forgejo PAT, repo write (push the release branch and tag, and create/append the Forgejo release). You already use this on `archiver`. |
| `NAS_FORGEJO_REPO_WRITE_PAT` | PAT on the NAS Forgejo, repo write (create the NAS release and append every asset to it). |
| `GH_REPO_WRITE_PAT` | GitHub PAT, Contents: read & write: creates the GitHub release and appends every asset to it. Same PAT used as the GitHub push-mirror password. |
| `GH_REPO_READ_PAT` | **Required.** GitHub PAT with **no scopes** — read-only public data. Used by the republish guard, the tag's mirror confirmation and the install-matrix wait, all of which refuse to call GitHub unauthenticated: 60 requests/hour per IP is shared with everything else leaving this network. |
| `PYPI_API_TOKEN` | PyPI API token (`pypi-…`), named `whiskerless-forgejo-ci` and **scoped to this project**, not the account — a token that can publish to every project the account owns has no business on a self-hosted runner. PyPI accepts OIDC only from GitHub Actions, GitLab.com, Google Cloud and ActiveState, so a token is the only option that keeps publishing on Forgejo; see the rejection rationale in project-rules's VARIANCE.md. |
| `CLUSTER_FORGEJO_TAP_WRITE_PAT` | Forgejo PAT with write access to `SisyphusMD/homebrew-tap`, so the submit jobs can open formula and bottle PRs. Held at the **org** level, not on this repo. |
| `CLUSTER_FORGEJO_REGISTRY_PUSH_PAT` | Forgejo PAT with **`write:package`**, for the apt/dnf registries and for `prune-rcs` deleting from them. Held at the **org** level and shared with the sister repos' container pushes — one scope covers every package type. Needed because Forgejo scopes packages on their own: the repo-write PAT above cannot upload or delete a package, and fails with a 403 rather than anything obvious. |
| `GPG_SIGNING_KEY` | The armoured private half of the package signing key (`CCE50015D058E9BF`). Written to a tmp file **outside** the workspace and `docker cp`'d in separately, so it is never part of a build context. |

### Apple signing (org-scoped on Forgejo, read only by `release-macos.yml`)

The signed and notarized `.pkg` is built on the macOS 15 VM. Nothing is needed on
GitHub: no workflow runs there.

| Secret | What it is |
|---|---|
| `MACOS_APP_CERT_P12` | base64 of your **Developer ID Application** cert (`.p12`) |
| `MACOS_INSTALLER_CERT_P12` | base64 of your **Developer ID Installer** cert (`.p12`) |
| `MACOS_CERT_PASSWORD` | the `.p12` export password |
| `MACOS_APP_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `MACOS_INSTALLER_IDENTITY` | e.g. `Developer ID Installer: Your Name (TEAMID)` |
| `MACOS_NOTARY_KEY_P8` | base64 of your App Store Connect API key (`.p8`) |
| `MACOS_NOTARY_KEY_ID` | the API key's Key ID |
| `MACOS_NOTARY_ISSUER` | the API key's Issuer ID (a UUID) |

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
