# #232 AI review: take the 40,000-token output cap and verdict-parse fix from project-rules

- Kind: issue, state: closed, by cody, created 2026-11-19T12:30:04-08:00
- Labels: status:in-progress, type:bug; milestone: none

Copy of the canonical script from SisyphusMD/project-rules#105 (issues SisyphusMD/project-rules#103 and #104). The old 16,000-token output cap cut long reviews off before their verdict, and a </think> the model quoted could leak its reasoning ahead of the JSON so the verdict failed to parse. Cody approved the 40,000 cap on 2026-11-19.

## cody, 2026-11-19T16:36:47-08:00

Decision: Admin-merge the AI-review sync PR past its failing AI review check (Cody: "Yes"). Why: The required review runs main's old parser, which cannot parse a review of this diff (it quotes </think>); the copy is byte-identical to project-rules main and every other check is green.

Decided by: Cody, 2026-11-19.
