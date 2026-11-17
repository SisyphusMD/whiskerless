# #195 Protocol finding: register 0x01 = panel button event reports (a lead on the missing actions)

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:27-08:00
- Labels: none; milestone: none

_Recreated from GitHub issue [#5](https://github.com/SisyphusMD/whiskerless/issues/5), opened by @CryingPecan on 2026-08-08, when the GitHub copy became read-only._

---

From 12 days of continuous capture on a production ESP 1.4.4 robot (full context in the field report + PRs #2/#3):

**Register 0x01 fires on physical panel button presses and at no other time.** Labeled ground truth:

- Cycle press → `0x010201` (3 samples: guided session 07-26, owner resume 07-31, post-refill 08-07)
- Reset press → `0x010401` (4 samples: guided session 07-26, drawer session 08-01, plus two more narrated presses)

Pattern reads as `(button_id << 8) | press_type` with 0x01 = short press. Cycle = 0x02, Reset = 0x04 — bit-flag spacing suggests Power/Empty/Connect occupy 0x01/0x08/0x10 (unverified; owner hasn't pressed those yet).

**Why it matters:** if 0x01 accepts type-2 *writes*, it may synthesize panel presses — which would recover the missing actions (cycle trigger, reset/tare) that the recovered firmware never exposed as opcodes. That's an untraced write, so it's firmly behind the safety guard until designed as a careful opt-in experiment — but it's the best lead the capture has produced. Our robot is available as the testbed if you want to design that experiment together.

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-12:_

Confirmed. `0x01` takes type-2 writes, and the bit-flag spacing holds: Empty is `0x010801`, Power is `0x010101`.

`0x02010201` runs a clean cycle, `0x02010401` presses Reset. Both proven on 1.1.75 across several trials, register echoing the value back each time. They ship as HA buttons now, Empty and Power disabled by default since Power takes the robot off the network and nothing over MQTT brings it back.

One thing that does not work: only press type `01` can be synthesised. Writing type `02` (the 3 second hold) produces no event at all, so the filter wizard and every other hold-only chord is unreachable this way. Whisker's own cloud has no long press either.

Closing since the question is answered.
