# #218 Require opt-in for unknown LR4 command types

- Kind: issue, state: closed, by cody, created 2026-11-17T15:02:26-08:00
- Labels: status:in-progress, type:bug; milestone: none

The LR4 classifier currently treats unrecognized command types as no-ops, which lets them through by default. Require `allow_dangerous` for unknown types and add regression tests showing that known no-ops still pass and never-send commands remain blocked. This gives EVO support in #188 the same safety rule from day one.

This is a prerequisite for #188 alongside #217.

## cody, 2026-11-19T17:47:36-08:00

Claude (session f565c0c9) has this, on branch fix/218-unknown-command-opt-in.

## cody, 2026-11-19T17:50:00-08:00

Technical call: Every type byte other than 01 (read) and 02 (write) is unknown and needs allow_dangerous; the whole byte is read, so 0x12A00000 is no longer taken for a type-2 write. An unknown type aimed at a never-send opcode, register or panel value is NEVER, so the opt-in cannot unlock a reset. "Known no-ops" are the writes already proven to be discarded (0x1A-0x1C) and stay SAFE. Hazard.NOOP is removed and CommandType.NOOP becomes UNKNOWN. Why: Only types 1 and 2 were ever tested; "anything else = no-op" came from the initial commit with no trial behind it, and the safety module already refuses untested commands on cost, not proof. #188 asks for this rule from day one.

Decided by: Claude, 2026-11-19.

## cody, 2026-11-19T18:35:39-08:00

Done in #238, merged as 4d6d4de. Every command type other than 01 and 02 now needs allow_dangerous, and a never-send opcode, register or panel value is refused at any type. The commit review found the old parser read only the second type digit, so 0x11A30000 passed as a safe read with no opt-in; that case is now pinned in tests. The branch and worktree are removed. Next: #219, the other prerequisite for #188.
