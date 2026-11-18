# #216 Close pull requests opened on the GitHub mirror

- Kind: pull, state: closed, by cody, created 2026-11-17T14:37:51-08:00
- Labels: none; milestone: none
- refs/pull/216/head -> main, merged: True

Closes #215

Copy the project-rules workflow that redirects new GitHub pull requests to Forgejo. The GitHub mirror will enable only the pinned lockdown action after the workflow is mirrored.

Validated the canonical file with actionlint and yamllint.

## forgejo-actions, 2026-11-17T14:38:26-08:00

<!-- ai-review -->
**AI review** of `aec13f94d3`: Clean, well-scoped PR that adds the mirror-lockdown workflow for the GitHub mirror, updates the Renovate exclusion, adjusts the repo invariant test, and updates the CI-split doc. The workflow is properly guarded (server_url + owner check, pinned action SHA, minimal permissions) and all hunks map to the linked issue.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
