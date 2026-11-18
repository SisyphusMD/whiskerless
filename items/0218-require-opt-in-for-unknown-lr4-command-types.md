# #218 Require opt-in for unknown LR4 command types

- Kind: issue, state: open, by cody, created 2026-11-17T15:02:26-08:00
- Labels: status:ready, type:bug; milestone: none

The LR4 classifier currently treats unrecognized command types as no-ops, which lets them through by default. Require `allow_dangerous` for unknown types and add regression tests showing that known no-ops still pass and never-send commands remain blocked. This gives EVO support in #188 the same safety rule from day one.

This is a prerequisite for #188 alongside #217.
