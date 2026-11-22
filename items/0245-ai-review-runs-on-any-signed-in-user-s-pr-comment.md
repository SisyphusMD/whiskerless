# #245 AI review runs on any signed-in user's PR comment

- Kind: issue, state: closed, by cody, created 2026-11-21T11:50:12-08:00
- Labels: status:in-progress, type:bug; milestone: none

Copy SisyphusMD/project-rules#116 (merged in project-rules #117): `ai-review.yml` here still starts a review on any signed-in account's PR comment, so an outside account can queue up to 45-minute runs on the Studio model. The canonical file now runs the comment path only for someone who can push or wrote the PR.

Plan: replace `.forgejo/workflows/ai-review.yml` with the canonical file, unchanged (this copy matched the previous canonical exactly).

Requested by Cody 2026-11-21 ("yes to all").

## cody, 2026-11-21T12:18:29-08:00

Status: merged in #246, verified on main (the canonical gate from SisyphusMD/project-rules#117). A PR comment now starts an AI review only for someone who can push here or wrote the PR. Nothing left on this issue; the AGit PR residual is tracked on SisyphusMD/project-rules#57.
