# #201 fix: hopper never proven on ESP 1.4.4 — the dispense burst spans three messages, not one

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:29-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#11](https://github.com/SisyphusMD/whiskerless/pull/11), opened by @CryingPecan on 2026-08-18, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

## The bug

`_apply_activity` counts a dispense only when **more than one** `HopperDispensed` event arrives **in a single activity message**. On ESP 1.4.4 that never happens: every real dispense is published as **three separate single-reading activity messages** — the phase-0 step marker first, then the phase-1 fill gauge and phase-2 marker ~20 s later (the last two ~0.1 s apart).

Verified on 5 dispenses across our two 1.4.4 robots in the 24/7 raw capture. The shape is completely consistent; a one-message triple has never been observed on this firmware:

```
robot A  04:47:05  0x0C010A      robot B  17:52:04  0x0C0114
         04:47:15  0x0C1057               17:52:24  0x0C1041
         04:47:15  0x0C2078               17:52:24  0x0C2079
```

Consequences on 1.4.4:
- **Fresh install with a hopper: the capability is never sighted**, so all five hopper entities sit `disabled_by: integration` forever. Our robot B was converted 3 days ago, dispensed the next day, and has `hopper_seen` absent and everything disabled.
- **Existing installs only keep hopper entities via RESTORED/LEGACY evidence**, and go stale: robot A's `last_hopper_dispensed` is frozen at its last pre-rc.9 dispense while the wire shows two dispenses since. Every fill-gauge sample is discarded, so the learned hopper scale never advances either.

## The fix

The burst is now assembled **across messages**: each `HopperDispensed` reading is folded into a small `pending_dispense` {phase: value} buffer on `DerivedState` (serialized, so a consumer reload mid-burst doesn't lose it), and the dispense is believed once **two distinct phases** land inside a 60 s window.

The false positive the old gate guarded against — a type-1 diagnostic READ of 0x0C decoding to a single `HopperDispensed` — stays rejected, and I think the distinct-phase rule is actually a stronger form of the guard: reads return whatever the register last held, so repeated polls produce the *same* phase every time and can never assemble a two-phase burst, no matter how close together they land. (The old gate would have accepted two identical-phase readings in one message.)

One-message bursts (1.1.75) prove on the same message exactly as before — the existing tests and the integration triples pass unchanged.

## Tests

- split-across-messages burst proves the hopper and applies the fill gauge (the real 1.4.4 timing)
- repeated same-phase reads inside the window prove nothing
- two lone reads farther apart than the window prove nothing
- a burst interrupted by a consumer reload between phases still proves (round-trips through `as_dict`)

74/74 in `test_derive.py` + `test_events.py`; full suite green except the 15 pre-existing `test_link`/`test_mqtt` failures in my local py3.12 env (same ones as before, unrelated).

Caveat: window is 60 s on the strength of the captured ~20 s gap; if 1.1.75 ever splits a burst wider than that we'd miss it, but no such capture exists.

## cody, 2026-11-17T08:59:29-08:00

_@CryingPecan on GitHub, 2026-08-18:_

Two live corroborations since filing, from tonight's captures (both robots ESP 1.4.4):

1. **Two more dispenses, same three-message shape** (6th and 7th observed) — including one from a hopper that turned out to be physically **empty** (owner-confirmed): the auger ran on schedule and the phase-1 gauge flatlined at 64–65, the bare-auger empty-floor signature. That's a concrete picture of what this gate costs today: with the fill samples discarded, `hopper_out_of_litter` can never learn the floor, so an empty hopper goes unnoticed until someone looks inside.

2. **The ~20 s gap has an official explanation.** Whisker's LitterHopper docs state the auger runs *up to 20 seconds* per dispense, and the docs also describe the below-optimal decision being taken at cycle end with the dispense executing during the *next* cycle. The phase-0 → phase-1 gap matches the documented auger runtime exactly — so the split isn't publish jitter, it's the hardware: phase 0 marks auger start and the fill gauge reports after it stops. The 60 s window bounds a documented 20 s mechanism with margin (pushed a comment update to the branch saying so).

Related find while watching this robot, separate from this PR: the panel litter-level recalibration combo (long-press Cycle+Reset+Empty) echoed as `0x010E02` — the OR'd-bitmask press model holding up on a three-button chord — and register `0x69` read back as the stored optimal litter bed level on both our units (458 / 460, matching each unit's maintained level; the cloud doc's `optimalLitterLevel` was 450 on the unit before its anchor was reset). Annunciation 105 fired on that combo too, which would explain why nine plain Reset presses never raised it. Happy to write that up properly as a docs PR if useful.

## cody, 2026-11-17T08:59:29-08:00

_@CryingPecan on GitHub, 2026-08-18:_

On the CI failure: `Shell scripts and documentation links` failed with `FAIL 403 https://www.litter-robot.com/support/article/litter-robot-4-control-panel-button-functions/` — that's the external-citation check, not this change (no links added; the citation predates the branch, behind docs/devices/litter-robot-4/control-panel.md).

The page is alive: from a residential IP it returns 200 with both a browser UA *and* the script's own `whiskerless-ci` UA. So Whisker's WAF is blocking by IP reputation (GitHub's runner ranges), not by user-agent — which means a UA tweak in `packaging/check-external-links.sh` likely won't help, and this will flake for every PR until the WAF changes its mind or the script does. One option: treat 403 as "resolves" for this URL — for citation-rot purposes a WAF challenge still proves the path routes to something Whisker actively defends, and the failure mode the check exists for (article moved/deleted) shows up as 404/410, not 403.

All other jobs green (both platforms, both float/floor, integration, hassfest).

## cody, 2026-11-17T08:59:29-08:00

_@SisyphusMD on GitHub, 2026-08-18:_

Landed as `f28dc6a` on the Forgejo source, with you as the commit author — it will
appear here on the next mirror push. Thank you, this was a good catch and a well
argued one; the evidence in the description is what made it reviewable.

Five changes on the way in:

**The firmware framing was too narrow.** The description has 1.1.75 packing the
burst into one message and only 1.4.4 splitting it. Our own capture notebook has
robot 2 — an ESP **1.1.75** unit — splitting it too, phase-0 about twenty seconds
ahead of the phase-1/2 pair, and robot 1 has never dispensed at all. So a
one-message burst has never actually been observed on any robot, on either
firmware. That makes the fix a stronger statement than the PR claimed: the old
gate did not fail on one firmware, it required a shape the wire has never sent.
The constant's comment, the code comment and the commit message now say that.

**The burst is spent when it proves.** It stayed populated, so the trailing
phase-2 marker re-entered the proof arm moments later and moved
`last_hopper_dispensed` again for a dispense already counted. Cleared on proof
now. (I also tried refusing any burst re-assembling inside `DISPENSE_DEDUPE`,
which is wrong — two real dispenses can arrive close together and each gauge is
worth recording. `tests/integration/test_hopper_detection.py` catches that, and
did.)

**Restored phases are bounds-checked.** `from_dict` accepted any integer, but the
wire splits one 16-bit reading into a 4-bit phase and a 12-bit value. A stored
impossible phase would have counted toward the two-phase proof and let a single
later register read look like a dispense.

**The reload test claimed more than it delivers.** The library does round-trip a
half-assembled burst, but the coordinator writes the derived snapshot only when a
sighting fires, and a first phase fires nothing — so Home Assistant restarting
inside the ~20 s gap does lose that one dispense, and the next one proves it. The
test now says exactly that instead of implying HA survives it.

**Coverage.** The defensive parse was two uncovered statements; there is a test
for it now, plus one for a burst whose middle gauge message is lost, which is a
real case on a lossy link. `derive.py` is back to 100%.

Also added the CHANGELOG entry and a note on backlog #68 — if every fill sample
was being discarded, the learned hopper scale was starved, which may well be the
whole of that under-reporting. Worth a fresh measurement before chasing the span.
