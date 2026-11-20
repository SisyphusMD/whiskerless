# #234 Split cli.py into per-command modules

- Kind: issue, state: open, by cody, created 2026-11-19T16:33:57-08:00
- Labels: status:ready, type:chore; milestone: none

cli.py is about 3,300 lines and holds every subcommand. Split it into per-command modules behind the existing entry point, with no behaviour change. Kept out of #217 so that diff stays reviewable and #188 rebases once. Agreed with Cody on 2026-11-19 while settling the #217 design.
