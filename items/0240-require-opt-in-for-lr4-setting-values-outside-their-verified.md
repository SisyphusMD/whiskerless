# #240 Require opt-in for LR4 setting values outside their verified range

- Kind: pull, state: closed, by cody, created 2026-11-19T21:28:42-08:00
- Labels: none; milestone: none
- refs/pull/240/head -> main, merged: True

Closes #219

Every LR4 settings register in the safety guard's safe bank took any 16-bit value without an opt-in. `0x0216FFFF` went out as freely as the 20-minute wait that was actually tested, and debug mode (`0x05`) was in the bank although it has never been written.

Now each settings register has the range recorded in the technical call on #219: the domain the setting can hold, where writes were read back. A value outside that range is DANGEROUS and needs `allow_dangerous`. `0x05` has no safe value. Panel brightness (`0x0E`) is checked level by level, because a range on the packed value would pass `0x00FF`. The never-send and unknown-type checks still run first, so no value or opt-in unlocks a reset target.

`whiskerless set` used to connect and then hit the guard. It now refuses an out-of-range value before connecting, names the value that was typed, and points to `send --allow-dangerous`.

The new tests reject the following, and each one was seen to fail against `main`:
- a value one past either end of each register's range, and `0xFFFF`
- a 16-bit value on the 0/1 lockout flag
- any write to `0x05`
- a panel brightness level over 100 in either byte
- `set` connecting for a write the guard refuses

A test that pins the range table whole fails if a register is added at any value or dropped. Never-send targets are checked at several values with `allow_dangerous`. Every Home Assistant entity range and the integration test values are inside the new ranges.


## forgejo-actions, 2026-11-19T21:29:23-08:00

<!-- ai-review -->
**AI review** of `17da0fddbd`: Well-structured PR that replaces the flat safe-settings set with per-register verified ranges, adds per-byte checking for panel brightness, removes untested debug mode from the safe bank, and moves the CLI's refusal before the MQTT connect. Tests cover every boundary, pin the table whole, and re-verify never-send targets. Docs and CHANGELOG are consistent with the code.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
