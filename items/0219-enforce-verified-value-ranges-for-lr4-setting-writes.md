# #219 Enforce verified value ranges for LR4 setting writes

- Kind: issue, state: closed, by cody, created 2026-11-17T15:05:58-08:00
- Labels: status:in-progress, type:bug; milestone: none

Audit the LR4 settings that whiskerless allows at any value. Keep unconditional writes for settings whose full range is verified. For the rest, allow verified values by default and require `allow_dangerous` for unverified values. Add regression tests at the boundaries and confirm that never-send commands remain blocked.

This is a prerequisite for #188 alongside #217 and #218.

## cody, 2026-11-19T21:15:01-08:00

Claude (session 97baacb9) has this, on branch fix/219-verified-value-ranges.

## cody, 2026-11-19T21:19:11-08:00

Technical call: A settings write is SAFE only inside its verified range, checked on the full 16-bit value; anything outside it is DANGEROUS and needs allow_dangerous. "Verified" means the value lies in the setting's defined domain (an enum, a percentage, minutes since midnight, a seven-day mask, or the range the app offers) and live writes inside that domain were read back. The ranges:

| Reg | Setting | SAFE values | Evidence |
|---|---|---|---|
| `0x05` | isDebugModeActive | none | no write recorded (#91) |
| `0x0E` | panel brightness | each byte 0–100 | written at 5 and stock 40/50; HA ships 0–100 (see the question below) |
| `0x16` | clean-cycle wait | 3–30 | written at 3, 7 and 20; the app's span |
| `0x17` | keypad lockout | 0–1 | both written |
| `0x18` | night-light mode | 0–2 | enum, all three written |
| `0x19` | night-light brightness | 0–100 | percentage, `0x63`/`0x64` written |
| `0x1A` | panel sleep mode (discarded) | 0–1 | discarded writes at 0/1 |
| `0x1B`/`0x1C` | panel sleep/wake (discarded) | 0–1439 | discarded writes inside the day |
| `0x1D` | weekday sleep mask | 0–`0x7F` | seven-day mask; `0x00`, `0x01` and `0x7F` written |
| `0x1E`–`0x2B` | weekday sleep/wake | 0–1439 | distinct per-day writes read back |

The never-send checks still run first, so no value or opt-in unlocks them. The builders keep their clamps, so `whiskerless set` refuses an out-of-range value up front and says so, instead of quietly sending a different value. Why: These registers took any 16-bit value, including `0x05`, which has never been written. Anything past the tested range is a write nobody has seen land, and #188 needs the same rule per model.

Decided by: Claude, 2026-11-19.

## cody, 2026-11-20T00:29:24-08:00

Decision: Panel brightness stays sendable at 0-100 per level without allow_dangerous. Why: It is what the Home Assistant sliders already offer, and brightness is reversible; only 5, 40 and 50 have been written.

Decided by: Cody, 2026-11-20.

## cody, 2026-11-20T00:41:54-08:00

Done in #240, merged as 4df4531. Every LR4 settings register now has a verified range. A value outside it needs allow_dangerous, debug mode (0x05) has no safe value, panel brightness is checked per level (0-100, per the decision above), and never-send targets stay refused at any value. `whiskerless set` refuses an out-of-range value before it connects. Branch and worktree removed. Next: #188 still waits on #217 (LR4 provisioning bench test).
