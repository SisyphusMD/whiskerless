# #214 Release through a merged pull request

- Kind: issue, state: closed, by cody, created 2026-11-17T14:18:45-08:00
- Labels: status:blocked, type:feature; milestone: none

Part of SisyphusMD/project-rules#86. Reuse the existing qualified stable release intent to open a release pull request. Add maintainer dispatch to tag the exact merged commit and retain the integration, native package and prerelease checks.

Depends on SisyphusMD/project-rules#97.

## cody, 2026-11-17T18:10:38-08:00

Codex is implementing the two-step stable release on an isolated branch. Generated Renovate PR #220 confirmed issue-link and AI review pass, but existing tests still assert the legacy atomic main-and-tag push. The conversion will replace those assertions and retain the existing qualification and prerelease paths.
