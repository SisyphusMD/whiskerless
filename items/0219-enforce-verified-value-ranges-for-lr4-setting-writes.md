# #219 Enforce verified value ranges for LR4 setting writes

- Kind: issue, state: open, by cody, created 2026-11-17T15:05:58-08:00
- Labels: status:ready, type:bug; milestone: none

Audit the LR4 settings that whiskerless allows at any value. Keep unconditional writes for settings whose full range is verified. For the rest, allow verified values by default and require `allow_dangerous` for unverified values. Add regression tests at the boundaries and confirm that never-send commands remain blocked.

This is a prerequisite for #188 alongside #217 and #218.
