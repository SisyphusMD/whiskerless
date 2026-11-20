# #233 AI review: 40,000-token output cap and verdict-parse fix

- Kind: pull, state: closed, by cody, created 2026-11-19T12:31:06-08:00
- Labels: none; milestone: none
- refs/pull/233/head -> main, merged: True

Closes #232

Byte-identical copy of `.forgejo/scripts/ai-review.py` from SisyphusMD/project-rules#105 (tests live there):
- the model output cap goes from 16,000 to 40,000 tokens (`MAX_OUTPUT_TOKENS` overrides it), since hidden reasoning alone ran past 16,000 on long reviews;
- a cut-off answer fails closed with a status that says to split the PR or raise the cap, and every run logs token usage;
- a `</think>` the model quotes no longer leaks its reasoning ahead of the verdict and breaks the parse.
