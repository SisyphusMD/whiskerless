# #260 chore(gate): call the shared gate and AI review workflows

- Kind: pull, state: closed, by cody, created 2026-11-25T21:28:50-08:00
- Labels: none; milestone: none
- refs/pull/260/head -> main, merged: True

Closes #259

`ci.yml` and `ai-review.yml` carried copies of the gate and AI review jobs, and copies drift. They now call project-rules main's `gate.yml`, `gate-lint.yml` and `review.yml` (SisyphusMD/project-rules#78), as proven in SisyphusMD/homebrew-tap#34. They keep only the triggers, the concurrency groups and the one secret the jobs may see, `ISSUE_READ_TOKEN`. Check names stay the same; each calling job adds one check of its own (`CI / shared-gate` and so on), which nothing requires.

This PR is judged by the old copies, because `pull_request_target` runs main's files; the next PR here runs on the callers.

No tests: workflow wiring only, covered by project-rules' tests of the called files and the homebrew-tap proof run.

## forgejo-actions, 2026-11-25T21:30:21-08:00

<!-- ai-review -->
**AI review** of `ea74219823`: Clean workflow refactoring that replaces inline gate/review job copies with calls to project-rules' shared workflows, keeping triggers, concurrency, and the single secret in the caller. The security model (pull_request_target, scripts from main, no PR code execution) is preserved, the test is updated to match the new job names, and the change is a single concern linked to #259.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
