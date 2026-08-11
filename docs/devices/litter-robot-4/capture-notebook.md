# Litter-Robot 4 — capture notebook

Observations from long-duration MQTT captures that are not yet solid enough for the
reference docs.

[`registers.md`](registers.md) and [`compatibility.md`](compatibility.md) are meant to be
trustworthy: a row there carries a confidence tag, and PROVEN means a value was watched
moving in step with a physical event. Something seen once, during one cycle or one visit,
is not that — and this project has already been wrong three times by promoting a
plausible reading that was never live-tested. So it lands here first with its evidence
attached, and moves into the reference once a second capture reproduces it.

Newest first. Nothing here is load-bearing for the code.

## Capturing

Most of what this project knows came from owners running a subscriber for days at a time
and sharing the result. Any MQTT client works:

```
mosquitto_sub -h <broker> -p 8883 --cafile ca.crt -i <client-id> \
              -t 'prod/LR4/#' -F '%I %t %p'
```

**Never use the robot's serial as the client id.** It collides with the robot's own
connection and kicks it off the broker.

Two properties of the robot's output will corrupt a capture if you don't expect them:

- **State payloads are pretty-printed JSON**, indented with tabs, so a single state
  message spans ~40 lines in any line-oriented capture. Reassemble by treating the
  `<timestamp> <topic>` header as the record boundary and everything after it as
  continuation.
- **Activity events are backlogged under load.** During a cycle the robot emits faster
  than it publishes: events carrying a payload timestamp of `14:29:52` have been seen
  arriving 16 seconds later. Order activity by the payload's own `timestamp` field, never
  by arrival — sorting by arrival silently reorders the cycle.

## Watchlist

| Question | What would answer it |
|---|---|
| Does `catDetect` `2` ever coincide with a cat? | A visit narrated against the clock — `3` has meant a body in the globe 37 times out of 37 |
| What do `0x3C` / `0x66` measure? | They repeat per cycle — correlate the values against a cycle interrupted mid-way |
| What are `0x33`, `0x49`, `0x4A`, `0x5E`, `0x64`? | Perturb something physical and watch which one moves |
| What does the `0x3402C0` tick count? | It runs ≈2-minutely only between a visit and the cycle — change the clean-delay setting and see whether the count follows |
| Why does an automatic cycle get a `0x34` pre-marker and a commanded one not? | More automatic cycles; check whether `0x1064`/`0x1065`/`0xE065` vary with anything visible |
| Is the `catWeight` divisor 50 or 100? | **A narrated visit** — a known, weighed cat in the globe at a noted time. Raw 809/914/1095 is either 16–22 lb or 8–11 lb, and unattributed readings cannot choose |
| Which ToF source drives `litterLevel`? | `0x58`/`0x59`/`0x5A` are all visible individually — check which one the published figure follows |
| Does anything above `0x7F` exist on 1.1.75? | An accumulating null result across many captures |

## Sessions

### 2026-08-10/11, 12h19m — five clean cycles, five cat visits

ESP 1.1.75 (`espFirmware`, all 409 state documents), LitterHopper attached. 1346 records:
409 state, 500 activity, 437 command. One continuous capture, no pod restarts.

Read twice before at 4h31m and 8h25m; each pass corrected the one before it, so the
figures here replace the earlier ones rather than adding to them.

**Every time below is the payload's own `timestamp`, not arrival,** and activity counts
are deduped on `(payload time, register, value)`. Timing this entry off arrival stamps —
which an earlier pass did — shifts cycle boundaries by seconds and invents differences
between events that are one redelivered message.

**Registers seen:** `0x01` `0x09` `0x0B` `0x33` `0x34` `0x37` `0x3B` `0x3C` `0x3E` `0x42`
`0x43` `0x44` `0x47` `0x48` `0x49` `0x4A` `0x4E` `0x4F` `0x57` `0x58` `0x59` `0x5A`
`0x5E` `0x64` `0x66`.

**Nothing above `0x7F`,** across five complete cat visits — the exact scenario that
should emit `0xBC` (visit duration) and `0xB9` (visit close). Neither has ever appeared
on this robot.

**`catDetect` `3` means a body in the globe; `2` does not.** All 37 `litterLevel`
collapses below 300 mm carried `3`; none carried `2`. What separates them is that long
runs of `2` hold with `litterLevel` sitting at exactly the figures the idle hours on
either side report, so the ToF is looking at an undisturbed litter bed throughout:

| run of `catDetect` `2` | duration | `litterLevel` |
|---|---|---|
| 08-10 18:24:37 | 2h15m51s | 432–434 |
| 08-11 00:45:05 | 25m18s | 433–434 |
| 08-11 01:13:59 | 41m24s | 435–441 |
| 08-11 01:56:37 | 10m05s | 439–440 |

That is 3h32m of the 12h19m capture — **29% of the time** — spent reporting a cat with an
empty globe. It is routine, not an anomaly. `2` also appears as a 6–9 s blip mid-cycle
(16:37:15, 20:50:12), where a rotating globe is a likelier cause than a cat.

**It is not a cat identity.** Whisker's multi-pet feature makes that a reasonable guess,
but within the single 16:26 visit the value ran `3 → 2 → 3 → 2 → 3 → 2 → 3 → 0` — seven
changes in 131 seconds, each one tracking whether the ToF could see the animal. No
identity code behaves that way. `1` never appears at all across 409 state documents, and
none of the 69 fields the state document carries names a pet, a profile or an index; the
only per-visit measurement the robot publishes is the raw weight on `0x09`. Whatever
attributes a visit to one of several cats, it is not happening on the device.

`models.py` decodes the field with `_bool()`, so any non-zero is `cat_detected=True`. On
this capture that reported a cat for 3h32m with an empty globe, and
`litter_is_sampleable()` — which wants `cat_detected is False` and `robot_status ==
"ready"` — discarded the whole window of otherwise ideal settled samples. Not yet a
reason to change the decode: `2` may mean a cat on the entry step, where the load cells
feel it and the ToF cannot see it.

**`robotStatus` `25` and `7` are live on 1.1.75, and they follow the scale rather than
the globe.** Both appear in the state documents (`7` ×125, `25` ×20) and `0x340006` puts
`6` on the activity stream, though no state document caught it. `registers.md` tags
`5`/`6`/`7`/`25` as 1.4.4-only; for `6`/`7`/`25` that is now wrong.

The same `4 → 25 → 7` path ran for a real visit (16:26, `catDetect` `3`) and for the
2h15m run with no body in the globe (18:24, `catDetect` `2`) — consistent with the
enum's own "weight on the scale" note. A third visit (16:42, 10 s) cleared straight back
to `4` and never cycled at all.

**The clean-cycle delay counts from the last `0x37` emission, not from `catDetect`
reaching `0`.** `cleanCycleWaitTime` reads `7` in all 409 state documents, and every
automatic cycle started 7m00s after the sensor last spoke, to within two seconds:

| last `0x37` | +7m | cycle (`0x34000A`) | error |
|---|---|---|---|
| 16:29:48 | 16:36:48 | 16:36:49 | +1s |
| 20:42:37 | 20:49:37 | 20:49:38 | +1s |
| 23:41:32 | 23:48:32 | 23:48:34 | +2s |
| 02:07:30 | 02:14:30 | 02:14:32 | +2s |

All four automatic cycles in the capture; the fifth was commanded and has no wait to
measure.

Measured instead from `catDetect` reaching `0`, the first two of those look erratic (+75s
and +0s) — because a late `0x37` blip at 16:29:48 restarted the timer more than
a minute after the state document had already published `catDetect` `0`. The sensor
going quiet and the cat leaving are not the same instant.

Four cycles is a strong correlation but they are all one capture, which is not the bar
this notebook sets. `registers.md` keeps `0x16` described as the wait it is, with no
claim about what starts the clock, until a separate capture reproduces this.

**`0x3C` and `0x66` are cycle-local and not cumulative.** Both fire only during a clean
cycle. Values rise through a cycle and then restart near the same figures on the next,
which rules out the lifetime counter they resembled in a single cycle — but a counter
that resets each cycle fits just as well, as do a position, a threshold or any
cycle-dependent sensor. Emissions cluster around phase changes without matching the four
phases one-for-one, so even "one per phase" is more than the data supports:

| | `0x3C` | `0x66` |
|---|---|---|
| 1 (commanded) | 568, 773, 1081, 1288 | 8478, 12360, 16642, 20611 |
| 2 | 536, 567, 773, 1081, 1288 | 8478, 12366, 12366, 16638, 20613, 20613 |
| 3 | 542, 568, 773, 1081, 1288 | 8475, 12368, 16635, 20604 |
| 4 | 568, 773, 1081, 1288 | 8479, 12369, 12369, 16631, 20608, 20608 |
| 5 | 568, 773, 1081, 1288 | 8476, 12368, 12368, 16628, 20609 |

Deduped on payload timestamp, `0x3C` emits the **same four values every cycle** — 568,
773, 1081, 1288 — with cycles 2 and 3 adding one earlier reading (536, 542) and shading
568 to 567. `0x66` likewise lands in four clusters, ~8477, ~12366, ~16635 and ~20609.
`0x5E` (10 emissions: 1736, 1740, 1745) and `0x64` (10: 1819, 1834, 1835, 1841, 1842)
are also cycle-only.

Pairing the two by position rather than by arrival, the ~16:1 ratio holds at two of the
four slots and misses at the other two: 773 → 12366 is 15.99 and 1288 → 20609 is 16.00,
but 568 → 8477 is 14.93 and 1081 → 16635 is 15.39. The misses are the interesting part —
16 × 530 = 8480 and 16 × 1040 = 16640 would both fit, and 530 is close to the extra 536 /
542 that only cycles 2 and 3 reported. So `0x66` may well be `0x3C` at sixteen times the
resolution, with `0x3C` not always publishing the reading that pairs with it. Still short
of a decode.

**`0x37` bit 0 mirrors `catDetect` going non-zero** — 51 emissions, every one of them
followed within a minute by a state document that agrees:

| `0x37` | next `catDetect` |
|---|---|
| `0x11` / `0x21` (bit 0 set) | non-zero |
| `0x10` / `0x20` (bit 0 clear) | falling to 0 |

That is a weaker claim than "tracks the cat", and deliberately so: bit 0 was set for the
2h15m run where `catDetect` read `2` with an empty globe, so it follows the same sensor
`catDetect` does rather than an animal. The `0x10` / `0x20` field varies independently —
`0x20` shows up at visit edges and `0x10` during the fine-grained toggling — and is
unexplained. A fifth value, `0x371021`, appeared once (18:54:42, mid-run).

`registers.md` rates `0x37` LOW and records the values it had seen as not cat-related;
these low ones plainly are. It also gives `catDetect` as 0/1/2 in the state document —
this capture repeatedly shows 3.

**`0x48` → `DFILevelPercent` at ≈0.70, on three independent cycles** — 28 → 20 (0.714),
32 → 22 (0.688), and 42 → 30 (0.714). The last is the cleanest of the three, being the
only one where the percent actually moved (20 → 30) rather than restating a value it
already held. This reproduces on 1.1.75 the ratio `registers.md` derived from a 38-cycle
capture on 1.4.4. The companion lasers (`0x49`, `0x4A`) fire in the same cycles and only
in cycles, reading 41/42/47 and 28/32/42.

**`0x58` / `0x59` / `0x5A` behave like the ToF trio `registers.md` says they are.** They
report in correlated bursts, ordered `0x58` → `0x59` → `0x5A` and spanning about three
seconds, though not every burst carries all three — the counts are 19 / 14 / 19. Their
values (166–405, 241–437, 135–292) sit in the same millimetre range as `litterLevel`, and
they cluster in visits, dropping well below the ~433 mm idle bed while a cat is in the
way. That corroborates from the activity stream what the `catDetect` `3` finding argued
from the state document: a body in the globe shortens the distance reading.

They are also silent during cycles — 0 of 19, 0 of 14 and 0 of 19 emissions land inside a
cycle window. That says the robot does not publish these while the globe turns; it says
nothing about what they would read if it did, so it is not independent support for
`litter_is_sampleable()` excluding cycles. Nothing new to decode here — just the three
sources behind `litterLevel`, visible individually.

**`0x34` and `0x4F` carry values far outside their enums, in two distinct shapes.**

`0x3402C0` (704) is a **≈2-minute tick that runs only between a visit ending and the
clean cycle starting** — before all four automatic cycles, and nowhere else in 12h19m:

| before cycle | ticks |
|---|---|
| 16:36:49 | 16:32:30, 16:34:30, 16:36:31 |
| 20:49:38 | 20:43:18, 20:45:18, 20:47:19, 20:49:19 |
| 23:48:34 | 23:45:03, 23:47:03 |
| 02:14:32 | 02:09:30, 02:11:31, 02:13:31 |

Two minutes apart to within a second, every time. Whatever it counts, it is not a status.

A second shape fires within a second of an automatic cycle starting and **never on a
commanded one**: `0x341064`+`0x341065` at 16:36:48, `0x34E065` at 20:49:38, `0x341064` at
23:48:34 and `0x34E065` at 02:14:32 — four of four automatic cycles, against none for
cycle 1, which was triggered by a written `0x02010201`. The value alternates between the
`0x10xx` and `0xE065` forms with no visible trigger. `0x4F1065` fired as cycle 2 ended,
putting the same `0x1065` on two different registers.

So neither register is reporting `robotStatus` / `robotCycleState` in these emissions.
Harmless today — `events_from_readings()` ignores both and status comes only from the
state document — but a warning for anyone tempted to drive status from the activity
stream, which is pushed and would otherwise be an attractive shortcut.

**A clean cycle, timed** (the first; triggered by a written `0x02010201`, which the robot
echoed as `0x010000` then `0x010201`):

Elapsed is measured from the first state transition, which landed 8s after the press:

| Elapsed | robotStatus | robotCycleStatus | robotCycleState |
|---|---|---|---|
| 0:00 | 4 → 10 | 1 → 2 | 1 → 3 |
| 0:54 | | 2 → 3 | |
| 1:03 | | 3 → 4 | |
| 1:57 | | 4 → 5 | |
| 2:06 | | | 3 → 12 |
| 2:13 | 10 → 4 | 5 → 1 | 12 → 1 |

So 2m13s transition-to-idle, 2m21s from the press itself. Measured between the same two
transitions, the second cycle ran 3m49s and the third 2m39s. `odometerCleanCycles`
increments on the activity stream (`0x3E`) at the *start* of a cycle, not the end.

**Three cat weights, and they sharpen the ÷50 question rather than settling it.** Four
`0x09` emissions carrying three distinct values: the two reading 809 share one payload
timestamp (`23:41:35Z`), so they are a single measurement redelivered — checked the way
this notebook says to check it, by payload timestamp and not by arrival.

| `0x09` raw | payload timestamp | ÷50 | ÷100 |
|---|---|---|---|
| 914 | 16:28:37Z | 18.28 lb | 9.14 lb |
| 809 | 23:41:35Z | 16.18 lb | 8.09 lb |
| 1095 | 02:07:33Z | 21.90 lb | 10.95 lb |

**Nothing here says which cat any reading belongs to.** Three cats share this robot and
five visits happened, three of which produced a weight — but one animal visiting three
times would also produce three readings, and a scale reading a shifting cat need not
repeat itself. "Three values, three cats" is an assumption, not an observation, and the
rest of this entry does not lean on it.

What the numbers do is strain the evidence that set the divisor to 50: raw 408, reported
twice, for the one cat ever weighed at ~8.1 lb on a household scale (408/50 = 8.16).
Under ÷50 the three readings above are 16.2, 18.3 and 21.9 lb, none near that animal.
Under ÷100 one of them is 8.09 lb — but that same divisor turns the old raw 408 into
4.08 lb, which is what ÷50 was adopted to fix. And 809 ≈ 2 × 408 (1.983), so those two
observations may be one animal on two different scalings rather than two animals. Raw 408
appears nowhere in this capture.

**Do not change the divisor on this.** One reading has the animals at 16–22 lb and the
other at 8–11 lb, and unattributed telemetry cannot choose. What decides it is a
*narrated* visit — a known cat in the globe, the time noted, the raw value read off
against a household scale. `registers.md` already warns that "a reported weight that looks
like double the animal means this went the wrong way"; a narrated weigh-in is what says
which direction that applies in.

**`0x57` −30 fires during a clean cycle and only during one** — five emissions at
14:30:17, 16:39:40, 16:39:41, 20:51:33 and 02:16:11, never once outside a cycle in
12h19m. It is neither once per cycle nor once per anything: the 16:39 cycle fired it
twice a second apart (two distinct payload timestamps, not a redelivery), and the 23:48
cycle fired it not at all — five emissions across four of five cycles. The positives (9, 14, 19, 20, 21, 24, 29,
70, 90, 99) land around visits and cycle edges. The hopper was attached and dispensing
throughout, so −30 is not a disconnect; a cycle-time emission fits the timing better than
the waste-drawer service that `HopperLinkChanged` cites.

This is not what makes `hopper_connected` read unknown: the coordinator already declines
to let an unnamed code overwrite an established link state, so −30 passes through
harmlessly except on a first report. Leave the tri-state alone.

`litterLevel` swings hard during a visit (432 → 110 → 430). It is a time-of-flight
distance in mm from the top of the globe down, so a cat in the way is measured to instead
of the litter surface and the reading collapses — 110 is the distance to the top of the
cat, not a change in the litter bed. whiskerless already discards these: see
`litter_is_sampleable()`, which requires a settled, idle robot with no cat detected.
