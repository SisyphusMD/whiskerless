# #198 Partially-decoded activity registers — open leads with 12 days of evidence

- Kind: issue, state: open, by cody, created 2026-11-17T08:59:28-08:00
- Labels: none; milestone: none

_Recreated from GitHub issue [#8](https://github.com/SisyphusMD/whiskerless/issues/8), opened by @CryingPecan on 2026-08-08, when the GitHub copy became read-only._

---

Omnibus of activity registers we've observed consistently but can't fully decode yet. All evidence from continuous production capture on ESP 1.4.4 (+ owner-narrated sessions); raw logs available.

- **0x57 (hopper link) positive values**: every visit runs the ritual 30 → mid-value → 19. The -15 disconnect and the dispense-phase fill gauge are solved (PR #3), but what 30/19 are, and what the mid-value measures (it loosely tracks visit weight — hopper load-cell?), remain open.
- **0x6F**: fires once at visit end, values 5-2182. Tested and REJECTED: minutes-since-last-visit, 0x57 echo, visit duration. Open.
- **0xB9**: closes every visit with value 1 or 2; no clean correlation found with weight presence, duration, or which cat. (An early tare-context guess was falsified — both values occur on ordinary visits.)
- **0x67**: an indexed triple (0x01xx/0x02xx/0x03xx) once per cycle, small varying counts. Torque/pinch counters?
- **0x0B annunciator values 102/105** paired with constant `0x33 = 34` at irregular hours: 105 is proven to fire on a Reset press (tare context); 102 and the 0x33 pairing are open.
- **Boot burst** (captured via a power cycle): 0x7F announces board identity (values match mbHardware/mbBom/etc.), 0x7E×7 init ticks, then 0x73/0x74/0x75 — 0x74 carried 490/530/998, calibration constants? None of these ever appear outside the boot window.
- **0x56 (drawer bay) code variance**: removal is a stable 10 (2/2 narrated pulls); re-insert codes VARY (14, 28) and 12 fires occasionally with the drawer seated (PR #3 decodes 10-vs-anything-else defensively, but the actual code meanings are open).

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-10:_

Update: the `0x0B` half of this is solved and shipped in `1f48c8d`.

`0x0B` is a status annunciator that fires alongside state transitions and names the event. Every value is now labelled against a live observed event:

| value | meaning |
|---|---|
| 7 | bonnet removed |
| 9 | cat detected |
| 12 | filter wizard waiting |
| 20 | cycle running |
| 22 | ready |
| 102 | night light transition |
| 105 | reset / tare |

The "random housekeeping chatter" was never random. 102 fires on dusk, dawn and room light changes, caught when the capture happened to be running while someone flipped a light switch; 105 fires on a Reset press, physical or written. Credit to @CryingPecan for the labelling work.

Also resolved from the wider register hunt since this issue was filed:

* **`0x01` is the panel button register and it accepts writes.** The value is `<button bitmask><press type>`. This is what unblocked every action command.
* **The readable register file is `0x00`-`0x7F`**, 123 of 128 addresses answering, with one contiguous gap at `0x6A`-`0x6E`. Nothing above `0x7F` answers a read. Reads must be paced ~3 s apart or the robot stops answering and you will wrongly conclude a register is unimplemented.
* **`0x1D` is a per-day bitmask**, not a boolean.
* **`0x56` reports that the waste drawer moved but not which way** — that one is documented as an open problem rather than solved, with what would settle it.

Still open here: `0x10`-`0x15` (live counters, values change between passes), `0x2C`, `0x2F`, `0x30`, `0x33`, `0x48`-`0x4A`, `0x50`-`0x55`, `0x5E`, `0x64`, `0x73`-`0x77`, `0x7B`. Leaving this issue open for those.

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-12:_

Two of these moved, and one of them cuts against what is written up here, which is the interesting part.

**`0x6F`**: listed above as tested and rejected for visit duration. On a 1.1.75 pair it matches the weight-on-scale span to within 3 seconds in 8 of 8, and is omitted on every visit under 15 seconds. Meanwhile `0xBC`, the one actually named `CAT_VISIT_DURATION`, matches no span that could be constructed.

**`0xB9`**: clean threshold here. `1` for all 8 closes with `0xBC <= 19`, `2` for all 8 with `0xBC >= 23`.

Before assuming either result is wrong: the two robots here turn out to differ in **mainboard** firmware, not just ESP. `mbRevision` 89 vs 93, `mbBuild` 1 vs 2, `mbRevisionId` 41027 vs 41088, with `espFirmware` identical at 1.1.75 on both. That would explain a lot of the cross-robot disagreements on both sides. What does the 1.4.4 robot report for `mbRevision` and `mbBuild`?

**`0x57` positives**: the 30 → mid → 19 ritual matches here exactly. Worth flagging though that the register is not the hopper link. Positives showed up with the hopper physically off the robot, and `-15` fires for just opening the hopper drawer.

`0x67` still open here too.

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-16:_

A narrated power cycle put a first observation on two registers from the still-open list
above, and settled a decode that had been recorded backwards.

**`0x50` and `0x7B` are power-transition registers.** A shutdown emits `0x04`, `0x06`,
`0x50`, `0x72`, `0x7B` and nothing else in the capture does, with `0x50` reading the same
148 on both edges. That does not name them, but it does take them out of the
idle-chatter pile.

**`robotStatus` 1 and 3 are the down-stroke; 2 is the up-stroke.** Run separately:

| | sequence | `0x31` unitPowerStatus |
|---|---|---|
| power **down** | `0x340001` → `0x340003` | 1 → **0** |
| power **up** | `0x340002` → ready (4) | 0 → **1** |

An earlier capture saw `1 → 3 → 2 → 13` across an off *and* an on and could not say
which half was which; this repo had 1 written up as `powering_up`, which was wrong.
`0x31` moves after all — it had looked static because a mains→battery swap leaves it
alone.

**`0x32` is the sleep flag**, driven by holding Cycle. An LR4 has no menu and cannot be
given a sleep *time* at the panel at all, which is worth knowing before designing a test
around one.

**The `0x56` seat-only asymmetry is dead.** One robot was silent on the pull and spoke
on the seat (`0x560017`); the other emitted `0x56000A` **both ways**, an hour later. Same
firmware family, opposite behaviour.

**`0x57` rides along on a waste-drawer pull too**, with a negative code that differs per
unit — **−30** on one, **−215** on the other. More evidence against it being the hopper
link, on top of the positives you saw with the hopper physically detached.

**`0x6F` and `0xBC` co-emit.** `registers.md` said the two had never been seen on the
same robot; they landed in the same second — `0x6F0029` (41) with `0xBC000A` (10) — and
`0x6F` was exact again, matching a 41 s `0x37` `0x11`→`0x10` occupancy span. Ninth of
nine. `0xBC` = 10 is not a rival reading of the same thing: 10 s of settled weight inside
41 s of occupancy fits both decodes, and `0xB9` came in at `1`, matching its documented
`<19 → 1` threshold.

Still open from the list above: `0x10`–`0x15`, `0x2C`, `0x2F`, `0x30`, `0x33`,
`0x48`–`0x4A`, `0x51`–`0x55`, `0x5E`, `0x64`, `0x67`, `0x73`–`0x77`.

Still curious what the 1.4.4 robot reports for `mbRevision` and `mbBuild` — the two
robots here differ in mainboard firmware while reporting identical `espFirmware`, which
would explain a good deal of the cross-robot disagreement on both sides.

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-19:_

A fresh 3d22h capture (2026-08-15→19, two robots) touches four of these.

**`0xB9` — there is a clean correlation, but not against the things you tried.** You tested weight presence, duration and which cat. Try it against `0xBC`: of the 41 seconds carrying both, the split is **41 of 41** — forty at `0xB9 = 1` with `0xBC` in 0–15, one at `0xB9 = 2` with `0xBC` far above.

And there's a likely reason it looked uncorrelated: **`0xBC` leads `0xB9` by 1–2 seconds.** 35 of the 76 seconds carrying either carry only one, so a same-second join drops 16 of 57 `0xB9` emissions (28%) and 19 of 60 `0xBC` (32%). Correlate over a small window, not a single second.

**Every out-of-range value we have is one Reset artifact — which may matter for your `0x6F` range.** We caught `0x6F = 24608` (6.8 h, far outside your 5–2182). It is not independent:

```
13:11:48  0x01=[0, 1025]          <- Reset press
13:11:53  0x09=2960  0x6F=24608
13:11:57  0xB9=2     0xBC=15699
```

Nine seconds on one robot, straight after a Reset. Since a Reset re-tares the scale (your own `0x0B = 105` = `reset_tare` finding), the reading is that the load-cell-derived registers emit garbage briefly afterwards rather than that several registers independently produce bad durations. **Worth excluding Reset-adjacent seconds before decoding `0x6F`, `0x09`, `0xB9` or `0xBC`** — it may tighten your 5–2182 range, and it's a caveat on our own `0xB9` result above, since the single high sample sits inside this episode.

**`0x74` is not a fixed constant, but two boots can't say more than that.** Two boot windows, one per robot: 13, 251, 256, 492, 555, 557, 768, 1010 — near your 490/530/998 without matching any. That rules out one burned-in value; per-robot, per-configuration and per-boot all still fit. Repeated boots of the *same* robot would separate them.

**Two codes for your lists:** `0x0B = 103` (once — you have 102/105) and `0x56 = 23` (once, against `10` ×4 — you have 10/12/14/28).

**On `0x6F` and visit duration** — you have it tested and rejected, our `registers.md` has it matching 9/9. I think that's a definitional mismatch rather than a disagreement: we match it against the **weight-on-scale span**, not total occupancy, and separately read `0xBC` as seconds of *settled* weight. If you rejected it against occupancy, both results can stand. Worth checking which quantity your rejection used.

Finally, `0x33` held **34 in all 55 readings**, both robots, four days — so the `0x0B`/`0x33` pairing you note is real (19 seconds carry both, `0x33` beside `0x0B` 102 most often) but `0x33` itself will not move under passive capture. It needs a deliberate perturbation.
