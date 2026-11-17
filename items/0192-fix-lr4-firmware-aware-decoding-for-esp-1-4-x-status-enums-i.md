# #192 fix(lr4): firmware-aware decoding for ESP 1.4.x (status enums, is_cleaning, litter suppression, pic_firmware)

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:25-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#2](https://github.com/SisyphusMD/whiskerless/pull/2), opened by @CryingPecan on 2026-07-28, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

Follow-up to #1, first of the code PRs from the ESP 1.4.4 field install. Everything here is backed by labeled live captures (a guided button-press session where each press was announced and timestamped, then 42 hours of untouched natural operation — 17 cat visits, 15 auto cycles, every mapping observed repeatedly).

**The headline: ESP >= 1.4 remapped `robotStatus`.** `10` now means *clean cycle in progress* — on 1.1.x it meant cat/weight pause (and 13 meant cleaning). Decoding is now firmware-aware via `espFirmware` from the same state doc; robots that don't report a parsable version keep the legacy map, so nothing changes for 1.1.x. New 1.4.x values mapped: `5` bonnet removed, `6`/`7` post-visit countdown, `25` cat detected/weight on scale.

Also:
- `robotCycleStatus` 2→3→4→5→1 per cycle (15/15 observed) with transient `robotCycleState` 12/15 — added so mid-cycle docs stop reading `unknown_N`
- `is_cleaning` falls back to the cycle machine when `robotStatus` is unmapped (it was permanently False on 1.4.4, which broke the HA integration's status usefulness)
- litter level suppressed while cycling — ToF reads the rotating globe mid-cycle (captured 574 mm on a 460 mm fill), which previously published garbage percentages
- `pic_firmware` composed from the `mb*` fields in the local doc (matches the cloud's `10535.2560.4.4` format); was always null

10 new tests, fixtures taken from the real captured payloads. Full 42-h register/event analysis writeup available if you want it — includes things not in this PR (hopper register 0x57, panel-button event register 0x01, the 0x0C dispense triples, and an apparent second activity encoding: value families like 0x1064/0x2065 appearing on both 0x34 and 0x4F). Happy to open protocol-finding issues for those next.

## cody, 2026-11-17T08:59:25-08:00

_@CryingPecan on GitHub, 2026-07-28:_

Live capture upgrade: triggered a manual cycle from the Whisker app on the still-cloud 1.4.4 robot and rapid-polled the cloud model during it. The cloud named the exact phases for the integer march this PR maps: `CYCLE_DUMP`(2) → `CYCLE_DFI`(3) → `CYCLE_LEVEL`(4) → `CYCLE_HOME`(5) → `CYCLE_IDLE`(1). Pushed a commit replacing the generic 'cycle' labels with the real names. Two corollaries: the legacy `3: home` label doesn't hold on 1.4.x (3 is the drawer-measurement phase — matches the DFI-register burst we captured locally during it), and the LitterHopper dispenses during CYCLE_LEVEL. Also: the cloud held `litterLevel` rock-steady through the whole cycle — Whisker itself suppresses mid-cycle ToF readings, which independently validates the suppression this PR adds. (`robotCycleState` strings seen: PROCESS / DELAY_1 / WAIT_OFF — plausibly the local 2-3 / 12 / 15; not yet pinned, left generic.)

## cody, 2026-11-17T08:59:25-08:00

_@CryingPecan on GitHub, 2026-08-01:_

One more decode, with the best provenance yet: **robotCycleState 4 = the mid-cycle cat-interrupt pause** — owner-witnessed live. A cat jumped into a running cycle; the wire showed the cat-detect burst + state 4 as the globe halted, robotStatus stayed 10 (clean cycle) throughout — state 4 is the ONLY pause signal. A Cycle press resumed, re-running the phase ladder from the top with no second odometer tick (the odometer counts cycle intents, not restarts). All 10 captures of value 4 in a 6-day window coincide with mid-cycle cat-detect activity. Pushed as `4: "cat_interrupt"` in ROBOT_CYCLE_STATE.

Also documented the waste-drawer gauge model in const.py from a narrated drawer-empty session: it's measurement-only on 1.4.4 (read by three lasers during the CYCLE_DFI phase; emptying the drawer or pressing Reset does NOT clear it — it re-measures next cycle), the % is ≈0.70× the primary raw laser (activity reg 0x48, r=0.999 over 38 cycles), and isDFIPartialFull means one drawer *sector* reads high (live-proven by a bunched fresh bag liner: 21% overall with partial-full=1).

## cody, 2026-11-17T08:59:25-08:00

_@CryingPecan on GitHub, 2026-08-01:_

Follow-up on cycle state 4 (cat_interrupt): **the pause is self-recovering**. A second natural mid-cycle cat interrupt (cloud-connected 1.4.4 robot this time) resolved with zero human input — the Whisker app sent "cycle interrupted" followed by "cycle completed", odometer incremented once. So the earlier manual Cycle press merely pre-empted the firmware's own resume timer. Consumers of the cat_interrupt state should treat it as transient: it clears itself once the cat leaves.

## cody, 2026-11-17T08:59:25-08:00

_@SisyphusMD on GitHub, 2026-08-09:_

Merged into `main` on the Forgejo source of truth (this mirror is read-only, so GitHub can't auto-close it). Your commits are preserved with you as author; the Claude Code trailers were stripped during the rebase, and the multi-paragraph bodies became single-line subjects to match the repo's commit convention. The rationale from your PR descriptions has been folded into the docs and CHANGELOG instead.

Shipping in 0.2.0. I'll send you a longer write-up separately — your work turned up something significant about our own `robotStatus` map that changed what we merged.
