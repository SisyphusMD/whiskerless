# #257 chore(gate): run the gate scripts and rules from project-rules main

- Kind: pull, state: closed, by cody, created 2026-11-24T19:11:41-08:00
- Labels: none; milestone: none
- refs/pull/257/head -> main, merged: True

Closes #256

This repo ran its own copies of the gate scripts and kept a copy of the rules for the AI review, and copies drift. `ci.yml` and `ai-review.yml` now fetch the scripts and `RULES.md` from project-rules main on every run and fail when they cannot (SisyphusMD/project-rules#78). The gate jobs and `ai-review.yml` are project-rules main's (6a6d41b4), and the copies are removed in the same change, so no run is left without either.

The reasons in test_workflow_security.py name project-rules main as the scripts' source. mirror-lockdown.yml is copied again for its source header.

Large diff: 890 of the removed lines are the deleted copies, and the added workflow lines come from project-rules main, where they were reviewed and tested.


## forgejo-actions, 2026-11-24T19:17:54-08:00

<!-- ai-review -->
**AI review** of `c43167210f`: The PR correctly implements issue #256: gate scripts and RULES.md are now fetched from project-rules main instead of local copies, the four script copies and .forgejo/RULES.md are removed, the workflows are updated to the project-rules versions, mirror-lockdown.yml gets its source header, and test_workflow_security.py reflects the new trust source. The security model is preserved (scripts come from a trusted branch the PR cannot modify), the large-diff justification holds, and the change is coherent with the linked decision in project-rules#78.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
