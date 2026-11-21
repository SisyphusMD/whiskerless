# #242 chore: default update checks, the Homebrew tap, links and blueprint imports to Forgejo

- Kind: pull, state: closed, by cody, created 2026-11-20T08:09:34-08:00
- Labels: none; milestone: none
- refs/pull/242/head -> main, merged: True

Closes #228

Sibling of SisyphusMD/dreame-valetudo#306. The CLI update check, the Homebrew tap (`brew tap --custom-remote`), package metadata, README links and the standalone notification blueprint (raw Forgejo import, `source_url`) now use the Forgejo primary. The component itself still installs through GitHub in HACS/Marketplace, and GitHub stays a full mirror. The README explains that stable v0.1.3 predates Homebrew and that the RC formula has bottles.

Checks: 1,593 library tests, Ruff and mypy pass locally on the merged tree.

Cold review (cx): one finding, fixed: the migration steps now say to reload automations before re-importing. Dropped the unrelated CONTRIBUTING sibling link, as in dreame.

## forgejo-actions, 2026-11-20T08:11:14-08:00

<!-- ai-review -->
**AI review** of `f502203b89`: PR #242 replaces GitHub URLs with Forgejo primary URLs across the CLI update check, Homebrew tap instructions, package metadata, README, docs, blueprint source_url, and tests, as specified by issue #228. The changes are focused, consistent, and well-tested; the new blueprint-link invariant test and updated update-check assertions cover the new behaviour.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
