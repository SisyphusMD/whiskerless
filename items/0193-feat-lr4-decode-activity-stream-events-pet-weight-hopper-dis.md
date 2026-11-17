# #193 feat(lr4): decode activity-stream events — pet weight, hopper dispense, hopper link (new reg 0x57)

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:25-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#3](https://github.com/SisyphusMD/whiskerless/pull/3), opened by @CryingPecan on 2026-07-28, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

Companion to #2 (independent — merges either order). This one unlocks the data that never reaches the state document: the coordinator previously used activity messages purely as a poll trigger and discarded their contents, but on a real robot three families of facts live *only* there.

**Pet weight works — it was just being thrown away.** Register 0x09 fires once per cat visit (int16/100 lb). 42 h of capture on my hopper-equipped LR4 (ESP 1.4.4): 21 readings, 17 visits, two clearly distinguishable cats (4.2–4.8 lb and 7.2–9.0 lb). The local state doc has no weight field at all, so `cat_weight` was permanently null before this.

**New register: 0x57 = hopper link.** Not in the register map. `0xFFF1` (-15) = link lost — live-proven by detaching the hopper, and it also fires on any bonnet movement (the hopper mounts on the back of the bonnet). Positive values (19/30/35–48) form a per-visit choreography whose middle value loosely tracks the measured cat weight — semantics open, so only the connected/disconnected distinction is decoded; raw passes through.

**Hopper dispense (0x0C) observed in the wild** — your `LITTER_HOPPER_DISPENSED` constant is real: a phase-tagged burst (`0x010A`/`0x1059`/`0x2078`-style) at the clean-cycle tail, 3 dispenses captured, litter restored to target each time. Raw values pass through undecoded until the phases are pinned.

Ships: `events.py` in the library (typed events, defensive extraction — unknown registers can never break it), coordinator folding events into `WhiskerlessData`, and three new entities (Last cat visit, Last hopper dispense, Hopper connected) plus Pet weight now actually populating. Activity-derived values are unknown after an HA restart until the next event — restore-on-restart deliberately left out to keep this reviewable; happy to follow up with it.

5 new library tests with fixtures copied verbatim from the captures.

## cody, 2026-11-17T08:59:25-08:00

_@CryingPecan on GitHub, 2026-08-01:_

Pushed two more activity-only registers to this PR, both live-proven on the production 1.4.4 robot during owner-narrated sessions:

- **0xBC = visit duration (seconds of settled weight)**, firing once at visit end. Proven against narrated visits: three deliberate ~5 s cat placements all reported 0 (and produced no 0x09), natural visits report 9-21 s. It's also the gate for the weight event — ~9 s+ always weighed, an owner-witnessed 8 s visit did not. A panel Reset press emits an unrelated large value (592) on the same register, so extraction caps plausible durations at 300 s. New 'Last visit duration' sensor; a duration event also stamps last_cat_visit, so hop-throughs too short to weigh still register as visits.
- **0x56 = waste-drawer bay events**: completely silent across 6 days of continuous capture until the drawer physically moved during a narrated bag change — 10 on pull-out, 14 on re-insert (flagged single-session evidence in the code; unknown codes pass through undecoded). New 'Waste drawer removed' binary sensor — a capability the cloud integration doesn't offer.

Both documented in const.py with the capture evidence.

## cody, 2026-11-17T08:59:26-08:00

_@CryingPecan on GitHub, 2026-08-06:_

Field correction to the drawer-bay decode, courtesy of a second narrated drawer pull 5 days after the first: **removal is consistently 10 (2/2), but the re-insert code VARIES** — 14 the first time, 28 the second — and 12 fires occasionally with the drawer seated. The original two-code decode latched the binary sensor at 'removed' when the unseen insert code arrived (observed live in production). Pushed a fix: 10 = removed, any other 0x56 value = seated — self-healing for future unknown codes.

Bonus finding from the same period (in const docs on the decode PR): the DFI cycle counter self-resets when the firmware *detects* a drawer empty — 0x42/0x45/0x46 zeroed on the first post-empty cycle whose dump-phase measurement confirmed the drop, seen on both bag changes.

## cody, 2026-11-17T08:59:26-08:00

_@CryingPecan on GitHub, 2026-08-07:_

One more addition, and it's a first-of-its-kind entity: **the hopper's fill gauge, decoded from dispense phase 1** (an 11-day capture happened to span a full hopper drain). The dispense triple's phases: 0 and 2 are invariant step markers (266/271/276, 120-121), but phase 1 tracked the hopper's contents — 89-92 while maintained near the owner's ~90% litter target all week, then declining monotonically (76, 70, 69, 68, 67, 66) as the hopper visibly ran down. It also retroactively explains the 87 we captured at hopper reattach during provisioning week.

New `Hopper fill (raw)` sensor — deliberately unitless: the true-empty and refill anchors are imminent on the production robot (owner is letting it run dry on purpose) and will calibrate a scale in a follow-up. Note the Whisker cloud offers NO hopper level at all (hopperStatus is just ENABLED/DISABLED), so this is a genuinely new capability, not parity.

## cody, 2026-11-17T08:59:26-08:00

_@CryingPecan on GitHub, 2026-08-08:_

The drain-to-refill arc completed live tonight, calibrating the fill gauge end to end — and yielding a **'Hopper out of litter' binary sensor** (pushed):

- 89-92 while maintained near target (weeks of baseline)
- monotonic decline while draining: 76 → 70 → 69 → 68 → 67 → 66
- **flatline at 66-70 with the hopper visually empty all day** — the floor reading of the bare auger. Crucially, the firmware NEVER flags empty: it ran a full, normal 3-phase dispense after every single cycle (5/5 that day), delivering nothing. Dispense frequency pinning at every-cycle is the behavioral corroborator.
- **immediate jump to 84 on the first post-refill dispense** (owner-narrated refill; fresh litter mounds unevenly, so a fresh pour reads slightly below the settled 89-92 band)

The empty and supplied bands don't overlap; the sensor uses <= 72. Neither the cloud integration nor the Whisker app offers any hopper-level or hopper-empty signal — the LR4's hopper has been silently measuring itself all along and nobody surfaced it.

## cody, 2026-11-17T08:59:26-08:00

_@SisyphusMD on GitHub, 2026-08-09:_

Merged into `main` on the Forgejo source of truth (this mirror is read-only, so GitHub can't auto-close it). Your commits are preserved with you as author; the Claude Code trailers were stripped during the rebase, and the multi-paragraph bodies became single-line subjects to match the repo's commit convention. The rationale from your PR descriptions has been folded into the docs and CHANGELOG instead.

Shipping in 0.2.0. I'll send you a longer write-up separately — your work turned up something significant about our own `robotStatus` map that changed what we merged.
