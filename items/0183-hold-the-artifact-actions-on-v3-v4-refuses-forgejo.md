# #183 Hold the artifact actions on v3 (v4+ refuses Forgejo)

- Kind: issue, state: closed, by cody, created 2026-11-17T07:51:31-08:00
- Labels: none; milestone: none

Renovate opened a major bump of `actions/upload-artifact` (v3.2.2 -> v7.0.2) and `actions/download-artifact` (v3.1.0 -> v8.0.2). It passes CI, but it would break the release: v4 and later throw `GHESNotSupportedError` on any server whose `GITHUB_SERVER_URL` is not github.com, which is every Forgejo run. `bottles.yml` and `release-macos.yml` pass the bottles and the signed `.pkg` between jobs through these actions, and PR CI never runs either workflow.

Plan: a `packageRules` entry that holds both actions below v4, so Renovate stops proposing the bump and closes the open PR. The held PR stays unmerged until then.

## cody, 2026-11-17T09:04:27-08:00

PR #184 adds the Renovate hold (`<4`) and a test pinning the workflow lines to v3; CI green, READY for merge. #182 left unmerged; Renovate should close it after #184 lands.
