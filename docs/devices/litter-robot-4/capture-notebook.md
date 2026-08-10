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
| What do `0x3C` / `0x66` measure? | They repeat per cycle — correlate the values against a cycle interrupted mid-way |
| What are `0x33`, `0x49`, `0x4A`, `0x5E`, `0x64`? | Perturb something physical and watch which one moves |
| Why do `0x34` / `0x4F` carry values outside their enums? | More cycle boundaries; check whether `0x1065` always pairs with a phase change |
| Is the `catWeight` divisor 50 or 100? | A second weighed animal — one visit reported 914 raw |
| Does anything above `0x7F` exist on 1.1.75? | An accumulating null result across many captures |

## Sessions

### 2026-08-10, 4h31m — two clean cycles, three cat visits

ESP 1.1.75, LitterHopper attached. 595 records: 178 state, 229 activity, 188 command.
One continuous capture, no pod restarts.

**Registers seen:** `0x01` `0x09` `0x0B` `0x33` `0x34` `0x37` `0x3B` `0x3C` `0x3E` `0x42`
`0x43` `0x44` `0x47` `0x48` `0x49` `0x4A` `0x4E` `0x4F` `0x57` `0x58` `0x59` `0x5A`
`0x5E` `0x64` `0x66`.

**Nothing above `0x7F`,** across three complete cat visits — the exact scenario that
should emit `0xBC` (visit duration) and `0xB9` (visit close). Neither has ever appeared
on this robot.

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

`773`, `1081`, `1288` and `8478` repeat exactly; the rest land within a few counts.
(Consecutive identical entries are redelivery — the same payload timestamp arrives twice
throughout this capture — so count distinct values, not messages.) The ~16:1 ratio
between the two registers holds at two points (773→12366, 1288→20613, both ≈16.00) and
not at the others, so treat it as unexplained rather than as a scale factor. `0x5E`
(1745, five times, always identical) and `0x64` (1819, 1834, 1841) are also cycle-only.

**`0x37` bit 0 tracks cat presence.** Now seen across three visits plus one mid-cycle
detection, toggling many times:

| `0x37` | next `catDetect` |
|---|---|
| `0x11` / `0x21` (bit 0 set) | 3 or 2 — cat present |
| `0x10` / `0x20` (bit 0 clear) | 2 or 0 — cat off the globe |

Only `0x10`, `0x11`, `0x20`, `0x21` were seen, so the high nibble is a second field of
its own. `registers.md` rates `0x37` LOW and records the values it had seen as not
cat-related; these low ones plainly are. It also gives `catDetect` as 0/1/2 in the state
document — this capture repeatedly shows 3.

**`0x48` → `DFILevelPercent` at ≈0.70, on two independent cycles.** Cycle 1: `0x48` = 28,
percent went to 20 (0.70 × 28 = 19.6). Cycle 2: `0x48` = 32, percent went to 22
(0.70 × 32 = 22.4). This reproduces on 1.1.75 the ratio `registers.md` derived from a
38-cycle capture on 1.4.4. The companion lasers read 42/41 (`0x49`) and 28/32 (`0x4A`).

**`0x34` and `0x4F` carry values far outside their enums.** `0x3402C0` (704),
`0x341064` (4196) and `0x341065` (4197) fired just before a cycle began; `0x4F1065`
(4197) fired as one ended. The *same* value `0x1065` appears on both registers, so these
are not `robotStatus` / `robotCycleState` readings in the documented sense. Harmless
today — `events_from_readings()` ignores both registers and status comes only from the
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

So 2m13s transition-to-idle, 2m21s from the press itself. The second cycle ran 3m49s
between the same state transitions. `odometerCleanCycles` increments on the activity
stream (`0x3E`) at the *start* of a cycle, not the end.

**One cat-weight event: `0x09` = 914 raw.** That is 18.28 lb at the current ÷50 divisor,
or 9.14 lb at the ÷100 it replaced. An earlier visit the same morning reported ≈8.19 lb
under ÷50, matching the one animal that has actually been weighed (~8.1 lb). Three cats
share this robot and only that one has been on a scale, so a second, heavier animal is
the straightforward reading and nothing here argues against ÷50. It does not confirm it
either: weighing the other two is what would, since ÷100 would put all three under 5 lb.

**`0x57` on a robot with a working hopper:** −30 (three times), and positives 9, 20, 21,
90, 99. The hopper was attached and dispensing throughout, so −30 does not mean
disconnected — but that is all it establishes. The code still treats every unnamed
negative as `connected=None` (an unknown fault, not a benign one), and nothing here
justifies relaxing that.

`litterLevel` swings hard during a visit (432 → 110 → 430). It is a time-of-flight
distance in mm from the top of the globe down, so a cat in the way is measured to instead
of the litter surface and the reading collapses — 110 is the distance to the top of the
cat, not a change in the litter bed. whiskerless already discards these: see
`litter_is_sampleable()`, which requires a settled, idle robot with no cat detected.
