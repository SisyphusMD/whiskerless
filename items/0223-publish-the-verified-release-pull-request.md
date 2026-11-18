# #223 Publish the verified release pull request

- Kind: pull, state: closed, by cody, created 2026-11-17T18:32:17-08:00
- Labels: none; milestone: none
- refs/pull/223/head -> main, merged: True

Closes #214.

Keeps existing qualification and prerelease workflows. Prepare Release opens a normal issue-linked PR and records the exact prepared commit. Publish Release verifies the merged tree and successful preparation for that head, checks the version stamps and latest candidate, and pushes only its annotated tag.

Vendors project-rules v0.3.1. Local validation: 1,492 tests and 99.18% branch coverage, the safety-module coverage gate, workflow and drift checks, plus a bare-origin fixture proving branch-only preparation, retries, and rejection of an unqualified PR head.

Large diff: The qualification workflow, tag-only publisher, verified upstream helpers, and their tests must change together to keep a working release path in this commit.

## forgejo-actions, 2026-11-17T18:41:32-08:00

<!-- ai-review -->
**AI review** of `5235379eac`: Well-structured conversion of the release path from an atomic commit+tag push to a two-step Prepare Release (opens a PR) / Publish Release (verifies the merged tree and pushes only the annotated tag). The verification chain in the publish workflow is thorough, the vendored helpers are updated consistently, and the invariant/security tests are correctly adapted.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
