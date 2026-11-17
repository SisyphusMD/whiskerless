# #184 ci: hold the artifact actions below v4 (v4+ refuses Forgejo)

- Kind: pull, state: closed, by cody, created 2026-11-17T08:09:07-08:00
- Labels: none; milestone: none
- refs/pull/184/head -> main, merged: True

Closes #183

Renovate PR #182 bumps `actions/upload-artifact` to v7 and `actions/download-artifact` to v8. Its CI is green, but it would break the next release: v4 and later throw `GHESNotSupportedError` whenever `GITHUB_SERVER_URL` is not github.com (read in the v7.0.2 dist, `isGhes()`), which is every Forgejo run. `bottles.yml` and `release-macos.yml` hand the bottles and the signed `.pkg` between jobs through these actions, and neither runs on a pull request.

- `.renovaterc.json`: a rule holds both actions at `<4`. Renovate should then close #182 on its next run.
- A test pins both halves: every artifact step's version comment says v3, and the Renovate ceiling exists. It fails on a v7 line (checked).

Reviewed with `qx review`; the findings that held up are applied.
