# #194 feat(lr4): expose panel display brightness (register 0x0E) in Home Assistant

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:26-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#4](https://github.com/SisyphusMD/whiskerless/pull/4), opened by @CryingPecan on 2026-07-28, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

Smallest of the series (independent of #2/#3). Your library already ships `set_panel_brightness()` and its wire test — but nothing decoded the read side and no entity exposed it. Live ESP 1.4.4 state docs carry `DisplayIntensityHigh`/`DisplayIntensityLow` as plain ints (my robot reports 40/50), so this just closes the loop:

- models: decode the two fields
- coordinator: `async_set_panel_brightness` with read-back verify of both bytes
- number platform: two CONFIG sliders — *Panel brightness (active)* and *(dimmed)*. A write composes the packed 0x0E value from the changed slider plus the current sibling byte, and refuses (with a clear error) until a state doc has reported current values, so we never blind-write half the register.

Write path not yet exercised on my robot — happy to run it live before you merge if you want a PROVEN tag on the round-trip; the encoding itself is your existing PROVEN 0x0E entry.

## cody, 2026-11-17T08:59:26-08:00

_@CryingPecan on GitHub, 2026-07-28:_

Write path now live-PROVEN on the ESP 1.4.4 robot: dimmed 50 → 45 → 50 via the new slider, each write committed and read back through the 0x0E verify, and the packed write left the active byte untouched (stayed 40) — no half-register clobbering. Running this build in production now.

## cody, 2026-11-17T08:59:26-08:00

_@CryingPecan on GitHub, 2026-08-08:_

**Labels question closed — behaviorally proven, two observations on the live 1.4.4 robot:**

1. Hi-byte forced to 5 (lo at 50) for three days: owner found the panel **maximally dim in full daylight** → the hi-byte (DisplayIntensityHigh) is the brightness applied in a BRIGHT room.
2. Restored to stock 40/50, owner darkened the room at night: the panel stepped **slightly brighter** as the interior night light came on → the lo-byte (DisplayIntensityLow) is the brightness applied in a DARK room.

So High/Low name the *ambient* light level, not the brightness rank — and the stock configuration is deliberately brighter at night (40 day / 50 night), which is why the field names looked swapped. Pushed the finalization: sliders renamed 'Panel brightness (bright room)' / '(dark room)', register + model docs updated with the proof. Entity keys unchanged (they match the firmware's DisplayIntensityHigh/Low). This PR is now final from my side.

## cody, 2026-11-17T08:59:26-08:00

_@SisyphusMD on GitHub, 2026-08-09:_

Merged into `main` on the Forgejo source of truth (this mirror is read-only, so GitHub can't auto-close it). Your commits are preserved with you as author; the Claude Code trailers were stripped during the rebase, and the multi-paragraph bodies became single-line subjects to match the repo's commit convention. The rationale from your PR descriptions has been folded into the docs and CHANGELOG instead.

Shipping in 0.2.0. I'll send you a longer write-up separately — your work turned up something significant about our own `robotStatus` map that changed what we merged.
