# #238 Require opt-in for unknown LR4 command types

- Kind: pull, state: closed, by cody, created 2026-11-19T18:05:57-08:00
- Labels: none; milestone: none
- refs/pull/238/head -> main, merged: True

Closes #218

The safety guard read only the second digit of a command's two-digit type byte. A type byte ending in 1 (`0x11`, `0x21`, …) was classified as a read and sent with no opt-in, so `0x11A30000`, a reset-class opcode, went out as `safe`. One ending in 2 inherited full write rules. Every other type was taken for a firmware no-op and also sent without opt-in, although only types `01` and `02` have ever been tried on a robot. The one unknown field that has been tried, the panel press type, was performed rather than ignored.

Now the whole type byte is parsed. Any type other than `01` or `02` is `dangerous` and needs `allow_dangerous`. A never-send opcode, register or panel value is refused at any type, so the opt-in cannot unlock a reset. Writes already proven to be discarded (`0x1A`–`0x1C`) stay `safe`. A raw panel-register write with an unknown type is still sent at most once.

`Hazard.NOOP` is removed and `CommandType.NOOP` is renamed `CommandType.UNKNOWN`. Nothing in the library or integration used them; the CHANGELOG lists the change under breaking changes. The protocol, codec, safety and contributor docs now describe the type as two digits and name the new refusal.

The new tests reject `0x11A30000` and `0x11AC0000` even with `allow_dangerous`, reject `0x03180001` without it, classify `0x12A00000` as `dangerous` rather than a safe report macro, and require at-most-once delivery for `0x12010201`. Each failed against `main`. The design is recorded on #218 (comment 39162).


## forgejo-actions, 2026-11-19T18:09:23-08:00

<!-- ai-review -->
**AI review** of `dcb6a90727`: The PR correctly fixes the type-byte parsing bug (only the second hex digit was read, so 0x11 was taken for a read), reclassifies unknown types as DANGEROUS requiring opt-in, keeps never-send targets unconditionally refused regardless of type, and adds focused regression tests that cover the new branches. The logic, docs, CHANGELOG, and test coverage all align with the issue and project rules.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
