# #196 Protocol finding: 0xX06Y value family on BOTH 0x34 and 0x4F — a second activity encoding?

- Kind: issue, state: open, by cody, created 2026-11-17T08:59:27-08:00
- Labels: none; milestone: none

_Recreated from GitHub issue [#6](https://github.com/SisyphusMD/whiskerless/issues/6), opened by @CryingPecan on 2026-08-08, when the GitHub copy became read-only._

---

Across 12 days of capture, a family of values appears on *two different* status registers' activity events:

- `0x34` (robotStatus) emitted 0x1064 (×35+), 0x2064, 0x1065
- `0x4F` (robotCycleState) emitted 0x1064, 0x2065

Identical values on different registers strongly suggests these activity events are not plain `(reg << 16) | val16` — a second encode path (phase-tagged? flag-carrying?) seems to exist. They fire at cycle start/end boundaries.

Related timing decode (semantics known, encoding not): **`0x34 = 0x02C0` fires every ~2 minutes during the clean-cycle WAIT countdown** — verified against every wait period in the capture (90+ samples). It's a countdown tick, but 0x02C0 doesn't fit any status enum.

Raw captures available for all of these.

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-12:_

Confirmed on two 1.1.75 robots, and it is a bit worse than a second encoding.

Over 50 hours, 67 of 208 deduped `0x34` emissions are not `robotStatus` enum members: the `0x_064`/`0x_065` family plus `0x02C0`. `0x4F` has five values outside its enum too, all on one robot, all in interrupted cycles. Anything decoding activity `0x34` through the status enum is producing garbage for a third of it.

The `0x02C0` tick reads exactly as described. Three ticks two minutes apart, stopping 13 seconds before a cycle that fired one second off `cleanCycleWaitTime`. It is the clean-delay countdown.

Encoding itself still open.

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-16:_

The `0x02C0` half has a window now, and the `0x10xx`/`0xE065` half has a trigger. The
encoding is still open, but both shapes are narrower than they were.

**`0x3402C0` fires only between a visit ending and a clean cycle starting.** All twelve
ticks in a 23h37m capture sit inside one of four windows, two minutes apart to within a
second, and none stray:

| cycle at | ticks |
|---|---|
| 16:36:49 | 16:32:30, 16:34:30, 16:36:31 |
| 20:49:38 | 20:43:18, 20:45:18, 20:47:19, 20:49:19 |
| 23:48:34 | 23:45:03, 23:47:03 |
| 02:14:32 | 02:09:30, 02:11:31, 02:13:31 |

The sixth cycle — the one released by waking, not by the timer — got no ticks at all,
which is what a countdown that does not run during sleep would look like.

**It does not count down.** A later capture caught two ticks with the cycle 92 s after
the last one, and every tick carried the same value (`0x02C0` = 704). So the tick count
and the gap to the cycle both vary; only the two-minute spacing has held. The 13-seconds
figure from the first pass does not generalise.

**The `0x10xx` / `0xE065` shape fires on timer-driven cycles and never on commanded
ones.** `0x341064`+`0x341065` at 16:36:48, `0x34E065` at 20:49:38, `0x341064` at
23:48:34, `0x34E065` at 02:14:32 — four for four on automatic cycles, against none for
the cycle triggered by a written `0x02010201`, and none for the wake-released one. The
value alternates between the two forms with no visible trigger.

**`0x4F1065` fired as a cycle ended**, putting the same `0x1065` on both registers.
That is this issue's premise landing on a second register in one capture.

One caution against the obvious conclusion: `0x34=1064` marking automatic cycles and
`0x01=0201` marking commanded ones held for two cycles and then broke — a cycle at
21:27:04 carried the button code with nobody at the machine. Not writing that one up as
answered.

Encoding itself still open.

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-19:_

Reproduced independently, on a separate 3d22h capture (2026-08-15→19, two robots, ESP 1.1.75). The family is real and it is on both registers:

| register | values | emissions |
|---|---|---|
| `0x34` | `0x1064` ×25, `0x1065` ×6, `0x3065` ×2, `0x2064`, `0x2065`, `0x4065` | 36, in 33 seconds |
| `0x4F` | `0xC065`, `0xE065` | 2 |

Of the 35 seconds carrying any of them, **none carries both** — so whatever this is, the two registers are not emitting it together.

The part worth adding: the high nibble is 1–4 on `0x34` and C/E on `0x4F`, and `0xE065` is exactly the value in this repo's own long-standing open question about a pre-cycle marker that "alternates `0x10xx` vs `0xE065`". That question and this issue are the same puzzle observed on two registers, and nobody had connected them. Both are now filed together in `docs/devices/litter-robot-4/capture-notebook.md`.

On the timing decode: confirmed, with one correction. `0x34 = 0x02C0` fired **164 times** in this window, spacing exactly 120 s, and it is **always alone in its second** (164 of 164 — no other register, and no other `0x34` value). It fires in bursts of 1 to 15 ticks. But it isn't a countdown: the value never changes, so it marks the wait rather than counting it down, and the burst length and the gap to the cycle are both variable. Bursts of 15 mean half an hour of ticking, which the tick itself doesn't explain.

One methodological note that cost us a wrong number here, in case it's useful against your captures: collapsing a second into `{register: value}` is lossy, because a register can emit several distinct values in the same second. `0x4F` does it in 182 of 489 seconds and `0x34` in 69 of 335 — so a scalar map understates exactly the two registers this issue is about.
