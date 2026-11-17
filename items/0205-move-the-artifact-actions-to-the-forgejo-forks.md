# #205 Move the artifact actions to the Forgejo forks

- Kind: issue, state: closed, by cody, created 2026-11-17T11:07:17-08:00
- Labels: none; milestone: none

The release path still uses `actions/upload-artifact` v3.2.2 and `actions/download-artifact` v3.1.0 (held there by #183 because GitHub's v4+ throws `GHESNotSupportedError` off github.com). Forgejo maintains forks with that check removed: `code.forgejo.org/forgejo/upload-artifact` and `code.forgejo.org/forgejo/download-artifact`.

Plan (Cody, 2026-11-17): switch `bottles.yml` and `release-macos.yml` to the forks, pinned by SHA with full `https://code.forgejo.org/...` URLs (upload `v5`, download `v7`, a v4+ protocol pair); replace the v3 pin test with one that pins the forks and forbids `actions/upload-artifact` / `actions/download-artifact` at any version; drop the Renovate `<4` hold and let Renovate track the forks (forgejo-tags datasource, held for hand review). Proven in a private proof repo with every publish step removed, on every runner label, before merge.

## cody, 2026-11-17T11:25:15-08:00

PR #206 (head 3b5f96e). Picked upload v5 + download v7: smoke run 38150 on a private proof repo passed upload, by-name download (own and cross-label), sha256 match and missing-artifact failure on ubuntu-latest, ubuntu-26.04-arm, macos-15-vm and macos-27-vm. Release-path proof runs in progress.
