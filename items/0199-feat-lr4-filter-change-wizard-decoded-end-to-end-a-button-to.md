# #199 feat(lr4): filter-change wizard decoded end to end + a button to start it

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:28-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#9](https://github.com/SisyphusMD/whiskerless/pull/9), opened by @CryingPecan on 2026-08-10, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

You know that mqtt command we texted you tonight? Here it is grown up, with everything the narrated wizard run taught us. All from a physical run of Whisker's documented panel chord (long-press Cycle+Empty) on the 1.4.4, wire-captured end to end.

## The chord cracked the button encoding open

The combo emitted `0x010A02`: **hi byte = button bitmask, lo byte = press type**. Cycle 0x02 | Empty 0x08 = 0x0A (Empty's bit now proven), press type 02 = long press vs the 01 shorts we had. So `PANEL_BUTTON_FILTER_CHANGE = 0x0A02`, and the untested space is now legible: long-press Empty alone (0x0802) is presumably your missing empty cycle.

## The wizard, fully choreographed

- **robotStatus 14 = changing_filter** — the local int your string map was waiting for. Held for the wizard's entire life. Mapping it also routes the wizard through LITTER_UNRELIABLE_STATUSES, which matters: we captured 575 mm mid-wizard on a 458 mm fill.
- **cycleStatus 14 → 15**: rotating-to-park → parked-and-waiting. Waits indefinitely; bonnet off/on during the wait triggers nothing (0x3A flips + annunciation only).
- **Reset is the return trigger** — the globe rides the normal level/home rails home, status 14 throughout, then 4/ready. So your existing panel_reset button already completes the flow.
- **odometerFilterCycles counts wizard entries, stamped at chord time** (2→3 live). Not a countdown — the app's replace-filter nag must be cloud-computed. A local robot never nags.

## Bonus: the 0x0B annunciator is now a dictionary

Every value labeled against a live event: 7 bonnet, 9 cat, 12 wizard-waiting, 20 cycle, 22 ready, and the 'random housekeeping' pair from issue #8 solved — **102 = night-light transitions** (dusk, dawn, and light switches; caught when the owner flipped a room light with the capture running) and **105 = reset/tare**. Shipped as documentation-grade `STATUS_ANNUNCIATIONS`.

## The button

'Park for filter change' goes through your existing press machinery unchanged — motor-gated by value, at-most-once, echo-confirmed, with robotStatus-14 as the state fallback (the wizard's persistence makes it the best fallback of the three buttons).

**The honest caveat:** the physical chord is fully proven; the *synthesised* chord write is the one untested link — first press-type-02 write anyone will have sent. Same posture cycle/reset were in when you merged them off three trials. Both robots are standing by; first trial settles it.

134 tests pass, six new ones covering the chord command, the motor gate, wizard status/phase decode, and the mid-wizard litter suppression.

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-10:_

Taking most of this. The chord capture is the piece that mattered: hi byte = button bitmask, lo byte = press type is the right reading, and it matches what I independently captured on the 1.1.75 (Power `0x0101`, Cycle `0x0201`, Reset `0x0401`, Empty `0x0801`). The `0x0B` annunciator dictionary is the best thing in the PR and closes #8. `robotStatus 14`, the wizard choreography, and the mid-wizard litter suppression are all going in.

The one thing that cannot ship is the button itself. You called the synthesised chord "the one untested link", so here is the test.

Three writes on 1.1.75, each with the activity stream captured end to end:

| written | robot answered | effect |
|---|---|---|
| `0x02010202` (Cycle long) | `0x010000` and nothing else | none |
| `0x02010402` (Reset long) | `0x010000` and nothing else | none, `nightLightMode` stayed 2 |
| `0x02010400` (Reset, press type `00`) | `0x010000`, then `0x010401`, `0x350000`, `0x0B0069` | a real Reset happened |

For comparison, a physical 3 second hold of Cycle emits `0x010202` on its own and the robot acts on it.

So an *unknown* press type (`00`) gets normalised to a short press and performed, while `02` produces no event at all. That is the shape of a value that is recognised and declined, not one falling through a default. The firmware performs short presses over MQTT and refuses long ones.

Independent corroboration, which I went looking for afterwards: pylitterbot's complete `LitterRobot4Command` list is 15 verbs, none of them a hold, and the one button verb is named `shortResetPress`. Whisker's own cloud has no long press either. It reaches the hold-only functions by writing the underlying setting instead, which is exactly what we already do for lockout (`0x17`), night light (`0x18`) and clump time (`0x16`).

That leaves the filter wizard genuinely unreachable from MQTT, because it is the one hold-only function with no backing settings register. Worth knowing rather than worth another trial.

Two smaller corrections while I am here:

* Empty alone is a **short** press, `0x0801`, not `0x0802`. Captured live, and `0x02010801` runs an empty cycle.
* Your `filter_change()` is classified `MOTOR`; our guard classifies panel button writes by value, and anything outside the proven set defaults to `DANGEROUS`. Moot now that the command is coming out, but noting it so the next command you add lands in the right bucket.

Your work is going into main as your commits, same as before. I will link them here when they land, then close this out.

## cody, 2026-11-17T08:59:28-08:00

_@SisyphusMD on GitHub, 2026-08-10:_

Merged as `1f48c8d`, authored to you, now on main and mirrored here.

What went in:

* `robotStatus 14` and both wizard cycle phases (`filter_park` / `filter_wait`), with the wizard routed through the litter-suppression set. Your 575 mm reading on a 458 mm fill is exactly why that matters.
* `ODOMETER_FILTER_CYCLES` documented as counting wizard *entries* rather than being a countdown, which explains why a local robot never nags.
* `STATUS_ANNUNCIATIONS`, the whole dictionary. This is the best thing in the PR and it closes #8.
* The button bitmask / press type structure, which matched my independent capture on 1.1.75.

What did not, and why, in full detail in my earlier comment: the synthesised chord `0x02010A02`. Press type `02` is declined on the write path across three trials, and an unknown type (`00`) is normalised to a short press and performed, so it is a deliberate refusal rather than an unimplemented case. pylitterbot's LR4 verb list has no hold command either and names its one button verb `shortResetPress`, so Whisker's own cloud cannot do it. The filter wizard is the one hold-only function with no backing settings register, which makes it genuinely unreachable over MQTT.

Two corrections carried into the docs: Empty alone is a short press (`0x0801`, now shipped as a disabled-by-default button), and the `MOTOR` hazard class is gone entirely. That last one came out of this PR indirectly. Arguing about whether your chord should be `MOTOR` or `DANGEROUS` made it obvious the class was never doing any work, since writing `0x01` reproduces the exact code the panel emits and every caller passed `allow_motor=True` unconditionally anyway.

Thanks for the capture work. Closing this one since the commit is in.
