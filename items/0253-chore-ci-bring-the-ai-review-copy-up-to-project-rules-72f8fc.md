# #253 chore(ci): bring the AI review copy up to project-rules 72f8fcc

- Kind: pull, state: closed, by cody, created 2026-11-23T21:31:33-08:00
- Labels: none; milestone: none
- refs/pull/253/head -> main, merged: True

Closes #252

Copies .forgejo/scripts/ai-review.py byte-for-byte from canonical SisyphusMD/project-rules 72f8fcc (SisyphusMD/project-rules#121, PR 122). Before this, a review whose answer was cut off at the output cap while still reasoning failed the check. Now it is asked once more under the answer schema. A cut-off mid-answer still fails closed. ai-review.yml is unchanged. Rollout tracked on SisyphusMD/project-rules#113.

## forgejo-actions, 2026-11-23T21:35:58-08:00

<!-- ai-review -->
**AI review** of `5fcd27c9c3`: Vendored sync of ai-review.py from project-rules 72f8fcc: adds a ReasoningCutOff path so a model cut off during reasoning (before any answer text) is retried under the schema, while a cut-off mid-verdict still fails closed. Logic, exception hierarchy, and retry messaging are correct; the diff is small, focused, and serves the linked issue.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
