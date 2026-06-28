# Packaging & release

`launcher.py` is the PyInstaller entry point; `entitlements.plist` carries the
hardened-runtime exceptions PyInstaller needs for notarization;
`changelog-section.sh`, `forgejo-release.sh`, and `github-release.sh` are release
helpers.

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
4. **Forgejo `publish.yml` `nas-pkg` job**: waits for the `.pkg` on the public
   Forgejo release, then **copies it to the internal NAS** release.

All three releases end up with the same notes + both binaries; PyPI has the
library. The release helpers are idempotent (create-or-reuse + replace assets),
so the two forges can write the same release in any order.

## Secrets

### On Forgejo (`forgejo.bryantserver.com/SisyphusMD/whiskerless` → Settings → Actions → Secrets)

| Secret | What it is |
|---|---|
| `CLUSTER_FORGEJO_REPO_WRITE_PAT` | Forgejo PAT, repo write (push the release commit/tag + create/append the Forgejo release). You already use this on `archiver`. |
| `NAS_FORGEJO_REPO_WRITE_PAT` | PAT on the NAS Forgejo, repo write (create the NAS release + receive the bridged `.pkg`). |
| `GH_REPO_WRITE_PAT` | GitHub PAT, Contents: read & write (Forgejo creates the GitHub release with it). Same PAT used as the GitHub push-mirror password. |
| `PYPI_API_TOKEN` | PyPI API token (`pypi-…`). OIDC trusted publishing isn't available on Forgejo, so this is a token. Scope it to the project once it exists. |

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
