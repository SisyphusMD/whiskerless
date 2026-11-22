# #247 chore(ci): bring the AI review copy up to canonical project-rules 64b857c

- Kind: issue, state: closed, by cody, created 2026-11-21T19:25:58-08:00
- Labels: status:in-progress, type:chore; milestone: none

Copy `.forgejo/scripts/ai-review.py` from canonical SisyphusMD/project-rules 64b857c, byte for byte (connect retry, malformed-answer re-ask, retry keeps first answer findings). In `.forgejo/workflows/ai-review.yml`, the actions/checkout step gets `ref: ${{ github.sha }}` and `persist-credentials: false`, and the review step env gets `BOT_LOGIN: forgejo-actions` (the #118 edits). No other files change apart from a CHANGELOG bullet where the repo keeps one.

Part of SisyphusMD/project-rules#113

## cody, 2026-11-21T20:29:03-08:00

Done in PR #248, merged as 1ca91af: ai-review.py and ai-review.yml are canonical 64b857c; CHANGELOG bullet added.
