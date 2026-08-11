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
| Does `catDetect` `2` ever coincide with a cat? | A visit narrated against the clock — `3` has meant a body in the globe 17 times out of 17 |
| What do `0x3C` / `0x66` measure? | They repeat per cycle — correlate the values against a cycle interrupted mid-way |
| What are `0x33`, `0x49`, `0x4A`, `0x5E`, `0x64`? | Perturb something physical and watch which one moves |
| What does the `0x3402C0` tick count? | It runs ≈2-minutely only between a visit and the cycle — change the clean-delay setting and see whether the count follows |
| Why does an automatic cycle get a `0x34` pre-marker and a commanded one not? | More automatic cycles; check whether `0x1064`/`0x1065`/`0xE065` vary with anything visible |
| Is the `catWeight` divisor 50 or 100? | A second weighed animal — one visit reported 914 raw |
| Does anything above `0x7F` exist on 1.1.75? | An accumulating null result across many captures |

## Sessions

### 2026-08-10, 8h25m — three clean cycles, two cat visits

ESP 1.1.75 (`espFirmware`, all 264 state documents), LitterHopper attached. 849 records:
264 state, 306 activity, 279 command. One continuous capture, no pod restarts.

This supersedes a first reading of the same pod's opening 4h31m, which counted three cat
visits. The third was not one — see `catDetect` below.

**Registers seen:** `0x01` `0x09` `0x0B` `0x33` `0x34` `0x37` `0x3B` `0x3C` `0x3E` `0x42`
`0x43` `0x44` `0x47` `0x48` `0x49` `0x4A` `0x4E` `0x4F` `0x57` `0x58` `0x59` `0x5A`
`0x5E` `0x64` `0x66`.

**Nothing above `0x7F`,** across two complete cat visits — the exact scenario that
should emit `0xBC` (visit duration) and `0xB9` (visit close). Neither has ever appeared
on this robot.

**`catDetect` `3` means a body in the globe; `2` does not.** All 17 `litterLevel`
collapses below 300 mm carried `3`; none carried `2`. What separates them is a run of `2`
that held for 2h15m41s (18:24:47→20:42:39) with `litterLevel` steady at 432–434 mm — the
same figures the idle hours on either side report, so the ToF was looking at an
undisturbed litter bed the whole time. `2` also appears as a 6–9 s blip mid-cycle
(16:37:15, 20:50:12), where a rotating globe is a likelier cause than a cat.

**It is not a cat identity.** Whisker's multi-pet feature makes that a reasonable guess,
but within the single 16:26 visit the value ran `3 → 2 → 3 → 2 → 3 → 2 → 3 → 0` — seven
changes in 131 seconds, each one tracking whether the ToF could see the animal. No
identity code behaves that way. `1` never appears at all across 264 state documents, and
none of the 69 fields the state document carries names a pet, a profile or an index; the
only per-visit measurement the robot publishes is the raw weight on `0x09`. Whatever
attributes a visit to one of several cats, it is not happening on the device.

`models.py` decodes the field with `_bool()`, so any non-zero is `cat_detected=True`. On
this capture that reported a cat for 2h15m with an empty globe, and
`litter_is_sampleable()` — which wants `cat_detected is False` and `robot_status ==
"ready"` — discarded the whole window of otherwise ideal settled samples. Not yet a
reason to change the decode: `2` may mean a cat on the entry step, where the load cells
feel it and the ToF cannot see it.

**`robotStatus` `25` and `7` are live on 1.1.75, and they follow the scale rather than
the globe.** Both appear in the state documents (`7` ×64, `25` ×13) and `0x340006` puts
`6` on the activity stream, though no state document caught it. `registers.md` tags
`5`/`6`/`7`/`25` as 1.4.4-only; for `6`/`7`/`25` that is now wrong.

The same `4 → 25 → 7` path ran for a real visit (16:26, `catDetect` `3`) and for the
2h15m run with no body in the globe (18:24, `catDetect` `2`) — consistent with the
enum's own "weight on the scale" note. A third visit (16:42, 10 s) cleared straight back
to `4` and never cycled at all.

**The clean-cycle delay counts from the last `0x37` emission, not from `catDetect`
reaching `0`.** `cleanCycleWaitTime` reads `7` in all 264 state documents, and both
automatic cycles started 7m00s after the sensor last spoke, to within two seconds:

| last `0x37` | +7m | cycle (`0x34000A`) | error |
|---|---|---|---|
| 16:29:50 | 16:36:50 | 16:36:51 | +1s |
| 20:42:37 | 20:49:37 | 20:49:39 | +2s |

Measured instead from `catDetect` reaching `0`, the same two cycles look erratic (+75s
and +0s) — because a late `0x37` blip at 16:29:46/16:29:50 restarted the timer more than
a minute after the state document had already published `catDetect` `0`. The sensor
going quiet and the cat leaving are not the same instant.

Two cycles in one capture is a correlation, not the anchor proven. `registers.md` keeps
`0x16` described as the wait it is, with no claim about what starts the clock, until a
later capture reproduces this.

**`0x3C` and `0x66` are cycle-local and not cumulative.** Both fire only during a clean
cycle. Values rise through a cycle and then restart near the same figures on the next,
which rules out the lifetime counter they resembled in a single cycle — but a counter
that resets each cycle fits just as well, as do a position, a threshold or any
cycle-dependent sensor. Emissions cluster around phase changes without matching the four
phases one-for-one, so even "one per phase" is more than the data supports:

| | `0x3C` | `0x66` |
|---|---|---|
| cycle 1 | 568, 773, 773, 1081, 1288, 1288 | 8478, 12360, 16642, 20611 |
| cycle 2 | 536, 567, 773, 773, 1081, 1288 | 8478, 12366, 12366, 16638, 20613, 20613 |
| cycle 3 | 542, 568, 773, 773, 1081, 1288, 1288 | 8475, 12368, 16635, 20604 |

`773`, `1081`, `1288` and `8478` repeat exactly; the rest land within a few counts.
(Consecutive identical entries are redelivery — the same payload timestamp arrives twice
throughout this capture — so count distinct values, not messages.) `0x5E` (1745, five
times, always identical) and `0x64` (1819, 1834, 1841) are also cycle-only.

The ~16:1 ratio between the two registers is still untested, and the obvious test does
not work: pairing each `0x66` with the nearest preceding `0x3C` yields ratios from 14.9
to 21.8, but activity events backlog by up to ~16 s under load, so arrival order does not
establish which two readings belong together. Pair by the payload's own `timestamp`
within a single phase before reading anything into the spread.

**`0x37` bit 0 mirrors `catDetect` going non-zero** — 29 emissions, every one of them
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

**`0x48` → `DFILevelPercent` at ≈0.70, on two independent cycles.** Cycle 1: `0x48` = 28,
percent went to 20 (0.70 × 28 = 19.6). Cycle 2: `0x48` = 32, percent went to 22
(0.70 × 32 = 22.4). This reproduces on 1.1.75 the ratio `registers.md` derived from a
38-cycle capture on 1.4.4. The companion lasers read 42/41 (`0x49`) and 28/32 (`0x4A`).

**`0x34` and `0x4F` carry values far outside their enums, in two distinct shapes.**

`0x3402C0` (704) is a **≈2-minute tick that runs only between a visit ending and the
clean cycle starting** — 16:32:30 / 16:34:30 / 16:36:31 before one cycle, and 20:43:18 /
20:45:18 / 20:47:19 / 20:49:19 before another. It never fires at any other time, on
either occasion. Whatever it counts, it is not a status.

A second shape fires 1–2 s ahead of a cycle and **only ahead of an automatic one**:
`0x341064` / `0x341065` before cycle 2 and `0x34E065` before cycle 3. Cycle 1 was
triggered by a written `0x02010201` and has no such marker. `0x4F1065` fired as cycle 2
ended, putting the *same* `0x1065` on two different registers.

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

**One cat-weight event: `0x09` = 914 raw.** That is 18.28 lb at the current ÷50 divisor,
or 9.14 lb at the ÷100 it replaced. An earlier visit the same morning reported ≈8.19 lb
under ÷50, matching the one animal that has actually been weighed (~8.1 lb). Three cats
share this robot and only that one has been on a scale, so a second, heavier animal is
the straightforward reading and nothing here argues against ÷50. It does not confirm it
either: weighing the other two is what would, since ÷100 would put all three under 5 lb.

**`0x57` −30 fires exactly once per clean cycle** — 14:30:17, 16:39:53, 20:51:33, three
of three cycles, and never once outside one. The positives (9, 14, 19, 20, 21, 90, 99)
all land around visits and cycle edges. The hopper was attached and dispensing
throughout, so −30 is not a disconnect; a routine per-cycle emission now fits the timing
better than the waste-drawer service that `HopperLinkChanged` cites.

This is not what makes `hopper_connected` read unknown: the coordinator already declines
to let an unnamed code overwrite an established link state, so −30 passes through
harmlessly except on a first report. Leave the tri-state alone.

`litterLevel` swings hard during a visit (432 → 110 → 430). It is a time-of-flight
distance in mm from the top of the globe down, so a cat in the way is measured to instead
of the litter surface and the reading collapses — 110 is the distance to the top of the
cat, not a change in the litter bed. whiskerless already discards these: see
`litter_is_sampleable()`, which requires a settled, idle robot with no cat detected.
