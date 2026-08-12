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

**A `prod/LR4/#` subscription carries every robot on the broker.** Split by the serial in
the topic before counting anything. The two robots here differ on several registers, and they
are **not running the same firmware** — see below — so a blended capture invents a register that
contradicts itself.

Three properties of the robot's output will corrupt a capture if you don't expect them:

- **State payloads are pretty-printed JSON**, indented with tabs, so a single state
  message spans ~40 lines in any line-oriented capture. Reassemble by treating the
  `<timestamp> <topic>` header as the record boundary and everything after it as
  continuation.
- **Activity events are backlogged under load.** During a cycle the robot emits faster
  than it publishes: events carrying a payload timestamp of `14:29:52` have been seen
  arriving 16 seconds later. Order activity by the payload's own `timestamp` field, never
  by arrival — sorting by arrival silently reorders the cycle.
- **The robot's clock is not the capture's clock.** One event carried a payload timestamp
  70 seconds *ahead* of its own arrival. Payload time is the right ordering key within a
  robot, but do not treat it as accurate wall-clock, and do not compare it across robots.

## Watchlist

| Question | What would answer it |
|---|---|
| ~~Is `catDetect` a bitfield whose bit 0 is the cat?~~ | **ANSWERED 2026-08-11.** Bit 0 = ToF sight line, bit 1 = load cell; all four values driven independently, 24 samples of perfect separation on a live cat |
| ~~What is `catDetect` bit 1?~~ | **ANSWERED 2026-08-11.** The load cell — an inert weight sets it with the beam clear, and Whisker's "excess weight" fault is bit 1 alone. Nothing to do with the hopper |
| Is `0x32` the sleep flag? | Two transitions in one capture, 2 s and 3 s ahead of `sleepStatus`. Toggle sleep by hand and watch it |
| Is `0x4C` "a cycle is owed"? | It has only ever been seen while asleep, so "a visit while asleep" fits the same data — catch a deferred cycle with sleep off |
| What do `0x3C` / `0x66` measure? | They repeat per cycle and now reproduce across two robots — correlate against a cycle interrupted mid-way |
| What are `0x33`, `0x49`, `0x4A`, `0x5E`, `0x64`, `0x71`? | Perturb something physical and watch which one moves |
| What are `0x0C`, `0x41`, `0x67`? | `0x0C` is **demand-driven** — robot 2 ran it while starved, stopped after a refill and has been silent for five cycles; robot 1 has never needed a dispense. Whether it needs the *hardware* is still open: run a cycle with litter scooped out of the globe and the hopper off |
| What are `0x5F`–`0x63`? | Seen once, bracketing robot 2's `0x350001` globe-motor fault (addendum) — catch a second fault |
| ~~What does the `0x3402C0` tick count?~~ | **ANSWERED 2026-08-11.** The clean-delay countdown — three ticks exactly 2 min apart, ending 13 s before a cycle that fired 1 s off `cleanCycleWaitTime` |
| Why does an automatic cycle get a `0x34` pre-marker and a commanded one not? | Looked settled (`1064` automatic, `0x01=0201` commanded) until a cycle carried the button code with nobody at the machine. Needs cycles where presence is certain |
| Is the `catWeight` divisor 100 for certain? | **The known-weight method does not work** — three trials gave divisors 72.4, 84.8 and 88.5, and an inert object sheds load against the globe wall. Needs a real cat, a clean tare, and a same-evening household weigh-in |
| Why does `0x57` fire at all? | Not the hopper link: positives appear with the hopper detached, `-15` appears for a drawer pull, and reattach is silent. Negatives `-15`, `-17`, `-30`, `-31` are all unreproducible |
| Which ToF source drives `litterLevel`? | `0x58`/`0x59`/`0x5A` are all visible individually — check which one the published figure follows |
| Does anything above `0x7F` exist on 1.1.75? | An accumulating null result — now two robots, 23h37m and 9m, still nothing |

## Sessions

### 2026-08-11 evening — narrated experiment night, both robots

The first session where the robots were *driven* rather than watched. Every action was
announced to the clock and matched against payload timestamps. That is why so much of it
outranks the passive captures below: the 2×2 `catDetect` table exists because both bits
were varied deliberately, not because two variables happened to move together.

**Both robots carry a LitterHopper.** The repo asserted for weeks that robot 2 had none,
and several conclusions were built on that; the owner corrected it mid-session and eleven
places were fixed. Nothing here rests on a hardware inventory nobody verified.

**`catDetect` is a two-bit field: bit 0 = time-of-flight sight line, bit 1 = load cell.**
All four values produced on one robot inside twenty minutes, each bit driven alone:

|  | ToF clear | ToF blocked |
|---|---|---|
| **no weight** | `0` — idle, litterLevel 427–445 | `1` — an arm in the beam, 203 / 165 |
| **weight** | `2` — an inert jug, 424 | `3` — a cat, 153–415 |

A live visit (20:45:16–20:46:38) gave 24 state samples with **perfect separation**: every
`3` at litterLevel ≤ 415, every `2` at ≥ 422, no exceptions, and the cat repositioned four
times with bit 0 following the sight line each time while bit 1 stayed pinned. Whisker's
own support documentation corroborates bit 1 independently — "blue light bar with partial
yellow flashing" is *excess weight detected, scale triggered over 30 minutes*, which is
bit 1 alone, and a Reset (which zeroes the scale) clears it.

That kills the old "two robots use different vocabularies, `3` vs `1` for a cat" reading.
Robot 2 emitted 0, 1, 2 **and** 3 in one evening; the split was an artifact of a
nine-minute sample.

**`robotStatus 5` exists on 1.1.75.** Bonnet lifts on both robots ran `4 → 5 → 4` (24 s
each) in lockstep with `isBonnetRemoved` and `0x3A`. The map said `5` was 1.4.4-only.

**Direction on the drawer bay is recoverable — from emission, not value.** Five seatings,
five removals, two robots, two different drawers: **every seat emitted `0x56`, every
removal was silent.** Seat values were 10, 11 and 12 for the same move, so the number
carries nothing. Three earlier rounds failed because they read direction out of the value.
`0x56` had never once appeared in the preceding 35 h of passive capture.

**`0x57` is not a hopper link signal in either direction.** Positives fired during a real
cat visit with the hopper in the owner's hand; `-15` fired for a drawer pull as well as a
full detach; reattach emits no distinct code at all. Four removals of the same drawer gave
`-17`, nothing, nothing, `-15` — and a Reset-cleared control produced a *third* outcome, so
pending-cycle state does not explain it. New negatives `-17` and `-31` appeared.

**`0x0C` is demand-driven, not evidence of hardware.** Robot 2 ran the dispense burst on
five straight cycles while its gauge read 58–60 (empty), the owner refilled it at ~07:50,
the next cycle reported **84** — the exact post-refill value `const.py` documents from an
11-day 1.4.4 arc — and it has been silent on all five cycles since. Its idle litterLevel
went 444 (starved) → 424 → **427–428, flat to 1 mm for seven hours**. Robot 1 held 430–437
for 35 h and has never dispensed once. So absence of `0x0C` means no deficit, not no
hopper — which is why `hopper_fill_percent` reads unknown on a well-fed robot.

**The clean-delay countdown is exact.** Visit closed 20:46:39, `cleanCycleWaitTime` 7,
cycle fired 20:53:38 — one second out. `0x3402C0` ticked at 20:49:24 / 20:51:24 / 20:53:25,
two minutes apart, stopping 13 s before the cycle. That is what the tick counts.

**`0x01` echoes physical presses.** Cycle → `0x01=0201`, Reset → `0x01=0401`, matching what
`commands.py` writes, confirmed seven times.

#### The weight divisor is still open, and the known-weight method does not work

The firmware **requires `catDetect == 3` to publish a weight**: a 10 lb jug held bit 1
alone for 172 s and produced no `0x09`; occluded so bit 0 also set, it published.

| true | raw | implied divisor | conditions |
|---|---|---|---|
| 9.1 lb (cat) | 805 | 88.5 | tare taken with hopper on, hopper off during the visit |
| 10.0 lb | 724 | 72.4 | clean tare, occluded, 42 s |
| 25.0 lb | 2119 | 84.8 | clean tare, occluded, 41 s |

Three trials, three divisors, 22 % spread — **not** the signature of a wrong constant, which
would land on the same wrong number every time. All read low (28 % / 15 %). The likely cause
is that an inert object sheds load against the globe wall while a cat settles its whole mass
on the pan. **÷100 is neither confirmed nor refuted**, and a divisor derived from these
points would be worse than the one in the code. Settling it needs a real cat with a clean
tare and a same-evening household weigh-in.

#### Refuted during the same session

Kept because the notebook's value is in what stopped being true, and each of these looked
clean before the next observation:

- **`0xB9` gates the weight report** — four visit-closes lined up perfectly (`1` = cat with
  a weight, `2` = phantom without), then a 25 lb trial closed `2` and published anyway. The
  gate is `catDetect` reaching 3.
- **`0x34=1064` marks automatic cycles and `0x01=0201` commanded ones** — held for two
  cycles, then a cycle at 21:27:04 carried the button code with nobody at the machine.
  Unresolved; do not write it up as answered.
- **`0x0C` would fire on a hopperless cycle with real demand** — predicted, and it did not.
  But the bed returned to its 427 target by levelling alone, so there was no true deficit
  and the test did not discriminate. Still open.
- **`0x0B = 105` is `reset_tare`, fired by a Reset press** — two narrated physical Resets
  emitted 22 (`ready`) and no 105 at all.

#### Also seen

`0x6F` (undocumented, four sightings at visit close: 82, 177, 103, 48) · `0x71 = 1` (second
sighting ever) · `0x0B = 8` (not in the annunciator table) · `0xBC`/`0xB9` **only ever from
robot 2** — robot 1 has never emitted either. This was read as "same build, so not
firmware-gated". **That was wrong**: the ESP versions match but the MAIN BOARD versions do not
(`mbRevision` 89 vs 93, `mbBuild` 1 vs 2, `mbRevisionId` 41027 vs 41088), so a firmware
explanation is back on the table for every register the two disagree on. Phantom visits shorter than the 300 s guard
(235 s, 172 s) would publish as genuine cat visits.

**Not done:** engineered sleep window, empty/power finales, a second seat on robot 1's
bottom drawer, and the `0x0C` deficit experiment.

### 2026-08-10/11, 23h37m — two robots, seven clean cycles, an 8-hour sleep window

One continuous capture, no pod restarts. 2336 records reassembled with zero orphan lines
and zero unparsed payloads.

- **Robot 1** `LR4C654321`, ESP 1.1.75, LitterHopper attached — the whole 23h37m. 2066
  records: 658 state, 715 activity (604 after dedupe), 693 command. Six clean cycles.
- **Robot 2** `LR4C123456`, ESP 1.1.75, LitterHopper attached — the last **9m34s**, from the moment
  BLE provisioning put it on this broker. 270 records: 73 state, 124 activity (103 after
  dedupe), 73 command. One commanded cycle and one cat visit.

Read three times before at 4h31m, 8h25m and 12h19m, then re-derived once more by an
independent audit with a fresh parser; each pass corrected the one before it, so the
figures here replace the earlier ones rather than adding to them. The audit's catch was
arrival-timed figures surviving in the clean-cycle tables of an entry whose headline rule
is payload timing — those numbers are corrected below.

**Every time below is the payload's own `timestamp`, not arrival,** activity counts are
deduped on `(payload time, register, value)`, and **every figure is for one serial.**
Timing this entry off arrival stamps — which two earlier passes did — shifts cycle
boundaries by seconds and invents differences between events that are one redelivered
message. **State documents carry a `timestamp` too**, and it is not decoration: arrival
lags it by up to 24 s on 516 of the 731 state records here. An earlier draft of this entry
used state arrival times and got the sleep boundary, the `0x32` lead and the whole `0x37`
correlation table wrong.

**Registers seen, robot 1 (28):** `0x01` `0x09` `0x0B` `0x32` `0x33` `0x34` `0x37` `0x3B`
`0x3C` `0x3E` `0x42` `0x43` `0x44` `0x47` `0x48` `0x49` `0x4A` `0x4C` `0x4E` `0x4F` `0x57`
`0x58` `0x59` `0x5A` `0x5E` `0x64` `0x66` `0x71`. The last eleven hours added `0x32`,
`0x4C` and `0x71`, none of which the 12h19m read had seen.

**Registers seen, robot 2 (25):** the same set less `0x09` `0x32` `0x3B` `0x4C` `0x57`
`0x71`, plus `0x0C` `0x41` `0x67` — three registers robot 1 has never emitted in 23h37m,
including during its own commanded cycle.

**Nothing above `0x7F` on either robot,** across ten complete cat visits — nine on robot 1
and one on robot 2, counting a visit as a run with `catDetect` bit 0 set. That is the exact
scenario that should emit `0xBC` (visit duration) and `0xB9` (visit close). Neither has
ever appeared on 1.1.75.

**`catDetect` behaves as if bit 0 tracked the cat.** This is the headline of the two-robot
window, and it replaces the previous entry's "`3` means a body, `2` does not" — which was
true of robot 1 and is not a description of the field. It is a correlation across two
machines, not a decode: `3 == 1 | 2` is arithmetic, and on its own does not distinguish a
bitfield from an enum that happens to number its states that way.

The two robots report a cat differently — and they do NOT run the same firmware (matching ESP,
differing main board). Robot 1 says `3`;
robot 2 says `1` and has never once emitted `2` or `3`:

| | `0` | `1` | `2` | `3` |
|---|---|---|---|---|
| robot 1, awake | 368 | — | 78 | 47 |
| robot 1, asleep | 124 | 1 | 9 | 31 |
| robot 2 | 46 | 27 | — | — |

`3` is `1 | 2`, and testing bit 0 against a `litterLevel` collapse below 300 mm (a body
in the way of the ToF) separates the two robots' vocabularies cleanly. Excluding cycles,
where the globe rather than the litter is being measured:

| | bit 0 set | bit 0 clear |
|---|---|---|
| robot 1, collapsed | **64** | 1 |
| robot 1, not collapsed | 15 | 427 |
| robot 2, collapsed | **12** | 0 |
| robot 2, not collapsed | 15 | 17 |

**76 of 77 collapses across both robots carry `catDetect & 1`.** The single exception is
08-11 07:09:24, `litterLevel` 129, `catDetect` `2`. It arrived five seconds after mosquitto
logged robot 1 re-establishing its session (07:09:19), which is suggestive and no more —
the document itself is complete and well-formed, and proximity is not evidence that it is
stale. Treat it as unexplained.

Note also the 30 documents (15 per robot) where bit 0 is set with no collapse. Those are
consistent with a cat the ToF cannot see, and equally consistent with bit 0 meaning
something other than a cat.

Bit 1 is something else, and **only the robot with a LitterHopper attached ever sets it.**
On robot 1 it holds for long stretches with the litter bed undisturbed:

| run of `catDetect` `2` | duration | `litterLevel` |
|---|---|---|
| 08-10 18:24:36 | 2h15m51s | 432–434 |
| 08-11 00:45:02 | 25m20s | 433–434 |
| 08-11 01:13:58 | 41m24s | 435–441 |
| 08-11 01:56:37 | 10m04s | 439–440 |

That is 3h33m of the 23h37m — and **all of it in the first half**, with no bit-1-only run
at all in the last eleven hours. The 12h19m read called this "29% of the time … routine,
not an anomaly"; over the full window it is 15%, and it is better described as clustered
than as routine. The hopper is the one hardware difference between the two robots, which
is what puts it on the watchlist above.

**It is not a cat identity.** Whisker's multi-pet feature makes that a reasonable guess,
but within the single 16:26 visit the value ran `3 → 2 → 3 → 2 → 3 → 2 → 3 → 0` — seven
changes in 136 seconds, each one tracking whether the ToF could see the animal. No
identity code behaves that way, and robot 2 uses a single value for every visit. None of
the 69 fields the state document carries names a pet, a profile or an index; the only
per-visit measurement the robot publishes is the raw weight on `0x09`. Whatever attributes
a visit to one of several cats, it is not happening on the device.

`models.py` once decoded the field with `_bool()`, so any non-zero became
`cat_detected=True`. That was right for robot 2 and wrong for robot 1, where it reported a
cat for 3h33m with an empty globe and made `litter_is_sampleable()` discard otherwise ideal
settled samples. The continuation below extended robot 2 to 499 documents and 13 bit-0
runs without a single `2` or `3`; all 37 of its cycle-excluded litter collapses carried bit
0. The decoder now uses `catDetect & 1`. This names the cat-correlated occupancy signal,
not the whole field: bit 1 remains unresolved.

**Robot 1 slept for 8 hours of this capture, and sleep changes what it reports.** The new
eleven hours are mostly a sleep window, so almost every difference from the 12h19m read
traces back to it. `sleepStatus` went `1` at 08-11 04:37:34Z and `0` at 12:37:36Z, with
`panelSleepTime` 1297 and `panelWakeTime` 337 — 21:37 and 05:37 in local time, which puts
the robot at UTC−7 and confirms the schedule is stored as local minutes. `weekdaySleepModeEnabled`
read 127 (all seven days) throughout.

While asleep the robot:

- **ran no clean cycle at all**, through four separate cat visits;
- **never published `robotStatus` `7` or `25`** — 125 and 23 of them while awake, and all
  165 sleeping state documents read `4`;
- produced both of the `catDetect` oddities above (the lone `1`, and the lone bit-0-clear
  collapse).

It did **not** go quiet: 165 state documents arrived on the usual ~5-minute cadence, and
the activity stream carried 112 emissions, most of them from the four visits. What is true
is narrower — during the long gaps *between* those visits, almost the only thing that
fires is `0x3B0001`, at 08:09:45, 09:10:02, 10:10:19 and 11:10:37, spaced 60m17s, 60m17s
and 60m18s. The one exception is a night-light group at 11:35:48–50 — `0x3B0000` with
`0x0B` 102 and 22, the LED switching off mid-gap.

**`0x32` may be the sleep flag.** `0x320001` fired at 04:37:32 and `0x320000` at 12:37:33 —
2 s and 3 s before `sleepStatus` changed in the state document — and the register appears
nowhere else in 23h37m. Two transitions in one capture is not this notebook's bar, so it
stays here rather than in `registers.md`.

**`0x4C` has only ever been seen asleep.** Nine emissions of `0x4C0001`, every one during a
sleeping cat visit (04:44, 07:08, 12:02, 12:25), then `0x4C0000` at 12:37:33 alongside the
`0x32` clear. "A cycle is owed" fits, and so does "a visit happened while asleep" — the
robot has never been observed owing a cycle while awake, because awake it just runs one.

**`0x71` is unexplained.** A single `0x710001` at 04:24:07, thirteen minutes before sleep,
and nothing else in the capture.

**`robotStatus` `25` and `7` are live on 1.1.75, and they follow the scale rather than
the globe.** Both appear in the state documents (`7` ×125, `25` ×23) and `0x340006` puts
`6` on the activity stream, though no state document caught it. `registers.md`'s enum
carries this already — `7`/`25` on both builds, `6` on 1.1.75 via the activity stream
only.

The same `4 → 25 → 7` path ran for a real visit (16:26, `catDetect` `3`) and for the
2h15m run with no body in the globe (18:24, `catDetect` `2`) — consistent with the
enum's own "weight on the scale" note. A third visit (16:42, 10 s) cleared straight back
to `4` and never cycled at all. **Robot 2's single visit ran the same `4 → 25 → 7` path**,
which is the first time this has been seen on a second machine.

**The clean-cycle delay counts from the last `0x37` emission, not from `catDetect`
reaching `0` — while the robot is awake.** `cleanCycleWaitTime` reads `7` in all 658 state
documents, and every *awake* automatic cycle started 7m00s after the sensor last spoke, to
within two seconds:

| last `0x37` | +7m | cycle (`0x34000A`) | error |
|---|---|---|---|
| 16:29:48 | 16:36:48 | 16:36:49 | +1s |
| 20:42:37 | 20:49:37 | 20:49:38 | +1s |
| 23:41:32 | 23:48:32 | 23:48:34 | +2s |
| 02:07:30 | 02:14:30 | 02:14:32 | +2s |

Measured instead from `catDetect` reaching `0`, the first two of those look erratic (+73s
and −1s) — because a late `0x37` blip at 16:29:48 restarted the timer more than
a minute after the state document had already published `catDetect` `0`. The sensor
going quiet and the cat leaving are not the same instant.

**The sixth cycle looks deferred by sleep.** It broke the pattern at +10m35s: the visit
ended at 12:27:01 with the robot asleep, its +7m would have landed at 12:34:01 inside the
sleep window, and the cycle fired at 12:37:36 — the same payload second in which
`sleepStatus` cleared. Sleep deferring an owed cycle fits that neatly, but **one cycle is
not a mechanism**, and the coincident timestamps cannot separate "the timer was suspended
and wake released it" from "wake independently triggers a cycle" or from a timer that ran
all along and was merely gated at the end. Four cats visited during the sleep window and
only one cycle ran at wake, so whatever the rule is, it does not queue one per visit.

Four awake cycles is a strong correlation but they are all one capture, which is not the
bar this notebook sets. `registers.md` keeps `0x16` described as the wait it is, with no
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
| 6 (after sleep) | 568, 773, **1080**, 1288 | 8473, 12374, 12374, 16623, 20599, 20599 |
| **robot 2** (commanded) | **563**, 773, **1075**, 1288 | 8346, 12397, 12397, 16498, 20588 |

Deduped on payload timestamp, `0x3C` lands in the **same four tight clusters every cycle** —
~568, 773, ~1081, 1288 — with cycles 2 and 3 adding one earlier reading (536, 542). The
12h19m read called these four identical values; the wider sample shows them drifting by a
count or two (567 in cycle 2, 1080 in cycle 6), so they are readings that repeat, not
constants. `0x66` likewise lands in four clusters, ~8477, ~12366, ~16635 and ~20609.
`0x5E` and `0x64` are also cycle-only.

**A second robot reproduces the shape.** Robot 2's first cycle hit 773 and 1288 exactly and
came within 6 of the other two, so these are close to firmware constants rather than
per-machine counters — but the small, consistent offsets mean they are readings, not
literals.

Pairing the two by position rather than by arrival, the ~16:1 ratio holds at two of the
four slots and misses at the other two: on robot 1, 773 → 12366 is 15.99 and 1288 → 20609
is 16.00, but 568 → 8477 is 14.93 and 1081 → 16635 is 15.39. **Robot 2 misses at the same
two slots** — 16.04 and 15.98 against 14.82 and 15.35 — which is the part that makes this
look structural. 16 × 530 = 8480 and 16 × 1040 = 16640 would both fit, and 530 is close to
the extra 536 / 542 that only cycles 2 and 3 reported. So `0x66` may well be `0x3C` at
sixteen times the resolution, with `0x3C` not always publishing the reading that pairs with
it. Still short of a decode.

**`0x37` bit 0 half-mirrors `catDetect`, and the `0x10` / `0x20` group is what decides
which half.** 85 deduped emissions on robot 1, matched against the first state document
within 60 s. The 12h19m read gave this as a clean two-row rule over 51 emissions; on the
full window, and on payload rather than arrival timestamps, only three of the four cells
hold:

| `0x37` | next `catDetect` | |
|---|---|---|
| `0x21` (bit 0 set) | non-zero 14/14 | holds |
| `0x11` (bit 0 set) | non-zero 22/23 | holds |
| `0x20` (bit 0 clear) | `0` 15/17 | holds |
| `0x10` (bit 0 clear) | `0` only 5/29 — `2` ×17, `3` ×6 | **does not hold** |

So "bit 0 clear means the cat is leaving" is true of the `0x20` group and false of the
`0x10` group, which is the reverse of the previous reading being a property of bit 0 at
all. A fifth value, `0x371021`, appeared twice.

Even where it holds this is weaker than "tracks the cat": bit 0 was set through the 2h15m
run where `catDetect` read `2` with an empty globe, so it follows the same sensor
`catDetect` does rather than an animal.

**`0x20` is not `catDetect` bit 1**, which is the obvious guess once `catDetect` is read as
a bitfield: `0x370020` is followed by `catDetect` `0` fifteen times against `2` twice, and
`3` never. What *is* true, on the thin evidence of two machines: robot 1 emits both the
`0x10` and `0x20` forms and sets `catDetect` bit 1, and robot 2 emits only `0x370010` /
`0x370011` and never sets it.

Robot 2 emitted 17 of them through its one visit, tracking `catDetect` `1` and `0` — though
not in a strict alternation.

`registers.md` rates `0x37` LOW and records the values it had seen as not cat-related;
these low ones plainly are. It also gives `catDetect` as 0/1/2 in the state document —
this capture repeatedly shows 3.

**`0x48` → `DFILevelPercent` at ≈0.70, now on five independent cycles across two robots**
— 28 → 20 (0.714), 32 → 22 (0.688), 42 → 30 (0.714) and 43 → 30 (0.698) on robot 1, and
27 → 19 (0.704) on robot 2's first cycle. Pair these on the value the percent *settles*
to, not whatever document sits nearest: pairing against the document *before* the emission
gives 1.000 / 0.625 / 0.476 and looks like a refutation. On robot 1 the first document at
or after each emission already carries the settled value; the one visible commit latency
is robot 2's, where the document sharing the emission's second still read 0 and the
settled 19 arrived two seconds later. All four robot-1 emissions moved the percent
(28 → 20, 20 → 22, 20 → 30, 32 → 30) — and the percent also moved in cycles 3 and 5
(22 → 20, 30 → 32) with **no** laser emission at all, so the drawer is re-measured every
cycle and `0x48` publishes only sometimes. This reproduces on 1.1.75 the ratio
`registers.md` derived from a 38-cycle capture on 1.4.4. The companion lasers (`0x49`,
`0x4A`) fire in the same cycles and only in cycles — 41/42/47/59 and 28/32/40/42 on
robot 1, 43 and 6 on robot 2.

**`0x58` / `0x59` / `0x5A` behave like the ToF trio `registers.md` says they are.** They
report in correlated bursts, ordered `0x58` → `0x59` → `0x5A` and spanning about three
seconds, though not every burst carries all three — the counts are 28 / 22 / 26 on robot 1
and 8 / 7 / 8 on robot 2 in nine minutes. Their
values (166–405, 241–437, 135–293) sit in the same millimetre range as `litterLevel`, and
they cluster in visits, dropping well below the ~433 mm idle bed while a cat is in the
way. That corroborates from the activity stream what the `catDetect` `3` finding argued
from the state document: a body in the globe shortens the distance reading.

None of the 28 / 22 / 26 fires while the globe turns — but `0x58` and `0x5A` (never
`0x59`) each fired four times at the exact payload second a cycle returned to idle,
reading the restored bed (~401–405 and ~280–283 mm), so the silence ends precisely at the
cycle boundary. That says the robot does not publish these mid-turn; it says nothing
about what they would read if it did, so it is not independent support for
`litter_is_sampleable()` excluding cycles. Nothing new to decode here — just the three
sources behind `litterLevel`, visible individually.

**`0x34` and `0x4F` carry values far outside their enums, in two distinct shapes.**

`0x3402C0` (704) is a **≈2-minute tick that runs only between a visit ending and the
clean cycle starting** — before all four awake automatic cycles, and nowhere else in
23h37m:

| before cycle | ticks |
|---|---|
| 16:36:49 | 16:32:30, 16:34:30, 16:36:31 |
| 20:49:38 | 20:43:18, 20:45:18, 20:47:19, 20:49:19 |
| 23:48:34 | 23:45:03, 23:47:03 |
| 02:14:32 | 02:09:30, 02:11:31, 02:13:31 |

Two minutes apart to within a second, every time. All 12 ticks in the capture sit in one of
those four windows — none stray. Whatever it counts, it is not a status.

The sixth cycle — the one that fired at wake — got **no ticks at all**, which is what a
countdown that does not run during sleep would look like.

Robot 2 emitted a single tick at 13:56:40, roughly 3½ minutes after its visit ended. That
is consistent with the same countdown starting, but the capture ends before any cycle could
follow, so it establishes nothing: a periodic marker or a post-visit one-shot fits that
lone event just as well.

A second shape fires within a second of a timer-driven cycle starting and **never on a
commanded one**: `0x341064`+`0x341065` at 16:36:48, `0x34E065` at 20:49:38, `0x341064` at
23:48:34 and `0x34E065` at 02:14:32 — all four awake automatic cycles, against none for
cycle 1, which was triggered by a written `0x02010201`. The sixth, wake-released cycle
got no marker either, which groups it with the commanded one rather than with the timed
four. The value alternates between the `0x10xx` and `0xE065` forms with no visible
trigger. `0x4F1065` fired as cycle 2 ended, putting the same `0x1065` on two different
registers.

So neither register is reporting `robotStatus` / `robotCycleState` in these emissions.
Harmless today — `events_from_readings()` ignores both and status comes only from the
state document — but a warning for anyone tempted to drive status from the activity
stream, which is pushed and would otherwise be an attractive shortcut.

**A clean cycle, timed** (the first; triggered by a written `0x02010201`, which the robot
echoed as `0x010000` then `0x010201`):

Elapsed is measured from the first state transition. The press itself has only an
arrival stamp — commands carry no payload timestamp — and the transition's payload time
is 3 s after it:

| Elapsed | robotStatus | robotCycleStatus | robotCycleState |
|---|---|---|---|
| 0:00 | 4 → 10 | 1 → 2 | 1 → 3 |
| 0:56 | | 2 → 3 | |
| 1:03 | | 3 → 4 | |
| 2:01 | | 4 → 5 | |
| 2:10 | | | 3 → 12 |
| 2:13 | 10 → 4 | 5 → 1 | 12 → 1 |

So 2m13s transition-to-idle, 2m16s from the press's arrival. Measured between the same
two transitions, the second cycle ran 3m44s and the third 2m36s. (The audit caught an
earlier version of these figures — 0:54 / 1:57 / 2:06, 3m49s, 2m39s — as arrival-timed
leftovers.) `odometerCleanCycles` increments on the activity stream (`0x3E`) at the
*start* of a cycle, not the end.

**Seven cat weights, and they re-opened the ÷50 question — since settled by the owner
(below).** Nine
`0x09` emissions carrying seven distinct values. The two reading 809 share one payload
timestamp (`23:41:35Z`) and are a single measurement redelivered; the 666 and 878 pairs
carry timestamps one and two seconds apart, so by this notebook's own rule they count as
distinct emissions even though one weigh-in is the likelier physical story.

| `0x09` raw | payload timestamp | ÷50 | ÷100 | |
|---|---|---|---|---|
| 914 | 16:28:37Z | 18.28 lb | 9.14 lb | awake |
| 809 | 23:41:35Z | 16.18 lb | 8.09 lb | awake |
| 1095 | 02:07:33Z | 21.90 lb | 10.95 lb | awake |
| 983 | 04:44:44Z | 19.66 lb | 9.83 lb | asleep |
| 666 | 07:09:25Z | 13.32 lb | 6.66 lb | asleep |
| 878 | 12:04:34Z | 17.56 lb | 8.78 lb | asleep |
| 939 | 12:27:02Z | 18.78 lb | 9.39 lb | asleep |

**Nothing here says which cat any reading belongs to.** Three cats share this robot, nine
visits happened and seven weigh-ins came out — but one animal visiting seven times would
also produce seven readings, and a scale reading a shifting cat need not repeat itself.
"Seven values, three cats" is an assumption, not an observation, and the rest of this entry
does not lean on it.

The weigh-ins do not map one-for-one onto the visits either. Five land inside or within
seconds of a `catDetect` bit-0 run, but 878 came two minutes after one and **1095 came
eleven minutes after the bit-0 run ended** — one second after the document in which the
trailing bit-1 stretch finally cleared to `0`. That does not say the cat had left — this entry does not know what bit 0 measures — and a weight
sampled during the visit and published late fits equally. Either way `0x09` is not reliably
co-timed with a bit-0 run, so pairing a weight to an animal by timestamp alone would be
guesswork on top of guesswork.

The wider sample does move the *spread*, which is the one thing unattributed readings can
speak to: ÷50 puts this household's cats between 13.3 and 21.9 lb, ÷100 between 6.7 and
11.0 lb. Neither range is impossible, and neither is evidence on its own.

What the numbers do is strain the evidence that set the divisor to 50: raw 408, reported
twice, for the one cat ever weighed at ~8.1 lb on a household scale (408/50 = 8.16).
Under ÷50 the three readings above are 16.2, 18.3 and 21.9 lb, none near that animal.
Under ÷100 one of them is 8.09 lb — but that same divisor turns the old raw 408 into
4.08 lb, which is what ÷50 was adopted to fix. And 809 ≈ 2 × 408 (1.983), so those two
observations may be one animal on two different scalings rather than two animals. Raw 408
appears nowhere in this capture.

**The owner has since attributed the range, and the divisor is back at 100.** The
household's cats weigh roughly 8–12 lb — the ÷100 range (6.7–11.0), not the ÷50 one
(13.3–21.9) — and under ÷100 this capture's 809 reads 8.09 lb, matching the ~8.1 lb
household weigh-in of the very cat that anchored ÷50. That re-frames the old raw 408
(≈ half of 809) as the anomaly needing explanation, not the units. An owner-attributed
*range* is weaker than a narrated visit — it cannot say which cat any single reading
belongs to — so a narrated weigh-in remains the test that would settle the divisor
beyond argument.

**`0x57` −30 usually fires during a clean cycle, but not only during one.** The 12h19m read
claimed "never once outside a cycle"; the extra eleven hours broke that. Seven emissions
now — 14:30:17, 16:39:40, 16:39:41, 20:51:33, 02:16:11, **02:52:34** and 12:39:05 — of
which six sit inside a cycle and one plainly does not. The 02:52:34 outlier came 2m37s
after an awake visit that produced no cycle at all (`robotStatus` ran `4 → 25 → 4` and
never reached `10`).

It is neither once per cycle nor once per anything: the 16:39 cycle fired it twice a second
apart (two distinct payload timestamps, not a redelivery), and the 23:48 cycle fired it not
at all. The positives (9, 14, 16, 18, 19, 20, 21, 24, 29, 49, 51, 56, 66, 70, 90, 99, 104)
land around visits and cycle edges.

**Robot 2 emitted no `0x57` whatsoever** in 9m34s covering a full cycle and a full visit —
the one window where robot 1 emits it constantly. That silence was once read as the
strongest evidence yet that `0x57` really is the hopper register `registers.md` calls it.
**That inference is void: both robots carry a LitterHopper.** Two identically equipped
machines disagree completely on the register, so whatever `0x57` tracks, it is not the
presence of the hardware. (The state document is no help either: on 1.1.75 it carries the
identical 69 fields on both robots — no hopper fields at all — so field presence
distinguishes nothing.)

This is not what makes `hopper_connected` read unknown: the coordinator already declines
to let an unnamed code overwrite an established link state, so −30 passes through
harmlessly except on a first report. Leave the tri-state alone.

`litterLevel` swings hard during a visit (432 → 110 → 430). It is a time-of-flight
distance in mm from the top of the globe down, so a cat in the way is measured to instead
of the litter surface and the reading collapses — 110 is the distance to the top of the
cat, not a change in the litter bed. whiskerless already discards these: see
`litter_is_sampleable()`, which requires a settled, idle robot with no cat detected.

**Robot 2's first nine minutes emit three registers robot 1 never has.** They all landed in
its first cycle after provisioning, and robot 1's own commanded cycle produced none of
them, so "commanded cycle" is not the trigger:

| register | emissions |
|---|---|
| `0x41` | `0x410000` ×2, 13:49:00 and 13:49:01 |
| `0x67` | `0x670118` (280), `0x670204` (516), `0x67031E` (798) — all three inside one second |
| `0x0C` | `0x0C0114` (276) at 13:49:35, then `0x0C103C` and `0x0C2078` at 13:49:55 |

The `0x0C` pair is worth a second look: `0x2078` is exactly twice `0x103C`, and splitting
each as a leading index and a value gives (1, 60) and (2, 120), also exactly double. That
is a guess about a two-sample register, not a decode. It is also the exact dispense
choreography `events.py` attributes to the LitterHopper, while robot 1 has emitted no
`0x0C` in six cycles. **Both robots carry a hopper**, so this is two identically equipped
machines behaving differently, and the burst distinguishes nothing about the hardware in
either direction.

Robot 2 also idles at `litterLevel` ~471 against robot 1's ~433 (a shallower bed, not a
protocol difference) and carried `DFILevelPercent` 0 → 19 across its first cycle.

**Addendum — a scan of the 2h13m after this entry's cutoff** (13:56:43Z–16:09Z; a scan,
not a full read — nothing above has been re-derived at the new boundary):

- Robot 2 ran six more cycles. The `0x0C` burst fired in four of them (phase-1 values
  58–60 and one 84), so it is a routine cycle phase, not a provisioning artifact. `0x67`
  recurs likewise; `0x41` has not recurred.
- Robot 2 latched a globe-motor fault — `0x350001` three times across 14:53:58–14:54:14,
  cleared by `0x350000` at 15:43:23 — bracketed by five registers never seen before on
  either robot: `0x5F`, `0x60`, `0x61`, `0x62` (one reading `0xFFF0`, −16) and `0x63`.
  A diagnostic bank around a fault fits; one episode decides nothing.
- Robot 2 emitted `0x370100` once — a fifth `0x37` value and the first with bit 8 set,
  so "robot 2 emits only `0x370010`/`0x370011`" did not survive two more hours.
- Robot 1: nothing new — still no `0x0C`, `0x41` or `0x67`, and still nothing above
  `0x7F` on either robot.

**Continuation audit through arrival 2026-08-12 01:07:55Z** (4,847 records total,
re-derived from the full pod log):

- Robot 2 reached 499 state documents: `catDetect` `0` ×423 and `1` ×76 across 13 bit-0
  runs, with no `2` or `3`. All 37 cycle-excluded litter collapses carried bit 0.
- Robot 1 reached 992 state documents: `catDetect` `0` ×776, `1` ×9, `2` ×114 and `3`
  ×93. Bit 0 carried 73 of 74 cycle-excluded litter collapses; the sole miss remains the
  reconnect-adjacent 07:09:24 document above. Across both robots the result is 110/111.
- `0x57` widened its observed positive range to 110: `0x57006E` at 19:14:22Z, during a
  cat-correlated state (`catDetect` `3`, `litterLevel` 172). One reading widens a range;
  it does not decode the value.
- Robot 2 emitted one new register, `0x650000`, at 16:10:04Z during cycle phase 2. It did
  not recur through this cutoff, so it stays a single observation with no proposed name.

**Connection behaviour** — this paragraph alone comes from the **broker's** log
(`kubectl logs` on the mosquitto pod), not from the MQTT capture, which carries only
`prod/LR4/…` messages and cannot see sessions at all.

Robot 1 reconnected twice, at 07:09:19 and 12:26:02, each logged as "already connected,
closing old connection" — the same line a client-id collision produces. Both new
connections came from the robot's own address (192.168.3.30), so this is the robot
re-establishing a session the broker had not yet reaped, *not* the collision a subscriber
using the serial as its client id would cause. Robot 2's first connection is 13:47:08 from
192.168.3.31, and the broker log has nothing for that serial before it.

**No state document went missing for more than ten minutes across the whole 23h37m.**
Whatever causes the "did not respond to a state request" warnings, it did not happen in
this window on this robot.
