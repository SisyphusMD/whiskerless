# Litter-Robot 4 — the control panel

Five buttons, no screen, no menus. Every setting the panel can reach is a press
or a three-second hold, alone or in combination.

**Source.** The button matrix below is Whisker's, from
<https://www.litter-robot.com/support/article/litter-robot-4-control-panel-button-functions/>.
It is reproduced here as our own table rather than copied verbatim, because the
useful thing is the *mapping to registers*, which is ours. CI checks that URL
still resolves on every run (`packaging/check-external-links.sh`) — a vendor
support page is exactly the kind of citation that rots silently.

**Read the Evidence column.** Whisker documents what a button does for a user.
Whether the robot *emits* anything we can see, and on which register, is our
observation — and the two have already disagreed once: our own docs claimed a
short Connect press did nothing, and it toggles the WiFi radio.

## Single press

| Button | Whisker says | What we have seen |
|---|---|---|
| Power | turns the unit on or off | write `0x02010101` proven 2026-08-16; emits `0x010101` |
| Cycle | starts a clean cycle; again to pause/resume | write `0x02010201` proven; emits `0x010201` |
| Reset | resets cat sensors / pauses / aborts / cancels sensor delay | write `0x02010401` proven; emits `0x010401` |
| Empty | starts an empty cycle | emission captured, **write still untested** (#13) |
| Connect | **toggles WiFi on/off** | write `0x02011001` proven 2026-08-16 — robot silent in 0.8 s, panel light **white**. No echo can escape; see below |

## Three-second hold

The value is `<button bits><press type>`; buttons OR together and `02` is a hold.

| Hold | Whisker says | Code | What we have seen |
|---|---|---|---|
| Cycle | 8-hour sleep mode, purple light bar | `0x0202` | **PROVEN 2026-08-16 on both robots.** Emits `0x010202`; drives `0x1A`, `0x1B`, `0x1C` and `0x32` in the same second |
| Reset | enables/disables automatic night light | `0x0402` | untested — should move `0x18`/`0x3B` |
| Empty | enables/disables cycle delay setting | `0x0802` | untested — should move `0x16` (`cleanCycleWaitTime`) |
| Connect | onboarding mode, blinking yellow | `0x1002` | emits `0x011002`; ~3 s to blinking yellow (timed 2026-08-16) |
| Power + Cycle | sends power to Aux1 | `0x0302` | untested |
| Cycle + Reset | control panel lockout | `0x0602` | untested — should move `0x17` (`isKeypadLockout`) |
| Cycle + Empty | moves globe to filter-change position | `0x0A02` | observed as `robotStatus` 14 |
| Empty + Connect | toggles USB power | `0x1802` | untested — should move `0x38` |
| **Reset + Empty** | **factory reset** | `0x0C02` | **refused unconditionally** (`PANEL_BUTTON_NEVER`) |
| **Reset + Connect** | **simulates unplugging** | `0x1402` | **refused unconditionally** (`PANEL_BUTTON_NEVER`) |

**Holds cannot be synthesised.** The firmware performs written press type `01`
and silently declines `02`, so every hold-only function is out of reach from
MQTT — the filter-change wizard included. Whisker's own cloud is no different:
pylitterbot's LR4 verb list has no hold, and reaches those settings by writing
registers, which is what whiskerless already does.

## Two things the panel tells you that no register does

- **A white light bar means the WiFi radio is off**, not that the robot is
  broken. It is the single most likely cause of "my robot disappeared", and a
  short Connect press restores it.
- **A purple light bar means sleep mode.** It is the only visible confirmation
  that a Cycle hold took.

## The filter

A flat carbon pad behind a cover on the *outside* of the globe, over the waste
drawer when the globe is home; reach it with the bonnet open. **There is no date
tab, printed mark or indicator of any kind** (checked on hardware 2026-08-16), and
no register reports filter state, so nothing in this project can tell a user when
to change it. Whisker says roughly a month.
