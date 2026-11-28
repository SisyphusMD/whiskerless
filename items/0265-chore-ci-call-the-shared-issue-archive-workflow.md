# #265 chore(ci): call the shared issue-archive workflow

- Kind: pull, state: closed, by cody, created 2026-11-27T07:11:28-08:00
- Labels: none; milestone: none
- refs/pull/265/head -> main, merged: True

Replaces the copied issue-archive job with the caller from project-rules main and deletes the copied script, which no longer runs.

Closes #264


## forgejo-actions, 2026-11-27T07:20:21-08:00

<!-- ai-review -->
**AI review** of `8bedcca317`: Clean, well-scoped CI change: replaces the copied issue-archive job and script with a call to project-rules' shared workflow, exactly as issue #264 asks. The schedule, concurrency group, and secret scoping are preserved; the deleted script is no longer referenced.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
