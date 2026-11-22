# #248 chore(ci): copy the AI review from project-rules 64b857c

- Kind: pull, state: closed, by cody, created 2026-11-21T20:17:58-08:00
- Labels: none; milestone: none
- refs/pull/248/head -> main, merged: True

Closes #247

Copies the canonical AI review script and the two #118 workflow edits from SisyphusMD/project-rules 64b857c (part of SisyphusMD/project-rules#113).

## forgejo-actions, 2026-11-21T20:18:53-08:00

<!-- ai-review -->
**AI review** of `50354ebc15`: The PR is a byte-for-byte vendored sync of the canonical AI review script from project-rules 64b857c plus the two #118 workflow edits (pinned checkout ref, persist-credentials: false, BOT_LOGIN) and a CHANGELOG bullet, exactly as issue #247 scopes it. The retry/re-ask/reply-bounding logic and the workflow hardening look correct and fail closed; no unrelated changes.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
