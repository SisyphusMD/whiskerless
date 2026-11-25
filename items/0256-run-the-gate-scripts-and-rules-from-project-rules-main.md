# #256 Run the gate scripts and rules from project-rules main

- Kind: issue, state: closed, by cody, created 2026-11-24T19:05:49-08:00
- Labels: status:in-progress, type:chore; milestone: none

Decided on SisyphusMD/project-rules#78 (2026-11-24): every repo runs the gate scripts, and the AI review reads the rules, from project-rules main instead of its own copies. Switch `ci.yml` and `ai-review.yml` to canonical (project-rules af7417d1; this also brings in the canonical commenter gate where it was missing), and remove the four gate script copies and `.forgejo/RULES.md` in the same change. Where present, copy `mirror-lockdown.yml` again for its source header. issue-archive.py stays a copy.

## cody, 2026-11-24T19:38:59-08:00

Landed in #257 (58402f08). The next PR is the first run of the fetched scripts.
