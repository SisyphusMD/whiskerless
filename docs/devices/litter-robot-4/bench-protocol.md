# At the robot: what is left to do

Written to be followed at the machine, in order, with a phone or laptop in hand.
Every step exists because something in this repo is currently **guessed**, and
each one says what would make it known. Narrate the times — the capture is
matched by the payload's own timestamps, so "about ten past" is not enough.

Before you start: note the wall-clock time and the robot you are at. The rolling
capture is already running (`lr4-capture` in namespace `homeassistant`), and its
history is read out of Loki afterwards, so nothing needs arming.

> **Two chords are never to be pressed.** **Reset + Empty** held is a factory
> reset — it wipes the broker config and costs a full re-provision. **Reset +
> Connect** held simulates a plug pull. Both are refused in software for the same
> reason; the panel has no such guard.

The 2026-08-16 session closed #45, #52 and most of #39 — see the
[capture notebook](capture-notebook.md) for what it found. What follows is what
that session did **not** answer.

---

## 1. The four untested hold chords (5 minutes, free)

The best value left. Each is a documented panel function that maps to a register
we already publish, so a mismatch is a live bug rather than a curiosity. Hold for
three seconds, note the time, then hold again to undo.

| Hold | Should move | What it would settle |
|---|---|---|
| **Reset** | `0x18` nightLightMode, `0x3B` LED | auto night light is a mode we expose; nobody has watched the panel set it |
| **Empty** | `0x16` cleanCycleWaitTime | we ship this as a 3–30 number; if the panel steps it differently our range is wrong |
| **Cycle + Reset** | `0x17` isKeypadLockout | panel lockout is a switch we expose |
| **Empty + Connect** | `0x38` isUSBPowerOn | `0x38` is documented as "mains present, not USB" and misnamed — this is the test that says so |

Tell me the time of each hold. If one of these moves a register that is *not* in
its row, that is the finding.

**Power + Cycle** (Aux1) is the fifth chord and has no expected register at all —
worth a hold purely to see whether it names one of `0x04`, `0x06`, `0x50`, `0x72`
or `0x7B`, the five that so far appear only during a power cycle.

## 2. Interrupt a cycle (2 minutes, free)

`0x3C` and `0x66` climb monotonically through a clean cycle and reset each time,
which looks like position or step counters. The watchlist's stated test is a
cycle that does not finish.

1. Start a clean cycle (panel Cycle press or the HA button). Note the time.
2. Part-way through, **lift the bonnet** — the interlock stops the globe.
3. Note the time. Reseat, press Reset if it asks, note that time too.

**What answers it:** whether `0x3C`/`0x66` freeze, reset, or keep climbing. A
counter that resets on interruption is a step index; one that holds is a position.

## 3. Which ToF drives litterLevel (2 minutes, free)

`0x58`, `0x59` and `0x5A` are all visible individually and nobody knows which one
the published figure follows.

1. With the bonnet open, **scoop a hollow in the litter on one side only**. Note
   the time and which side.
2. Level it again a minute later. Note the time.

**What answers it:** whichever of the three moves with `litterLevel` is the source.
A hollow on one side should move one sensor and not the others.

## 4. Does the hopper dispense need the hardware? (5 minutes)

`0x0C` is demand-driven — one robot ran it while starved and stopped after a
refill. Whether it needs the *hopper* or just the demand is open.

1. **Detach the hopper.** Scoop the globe well below the fill line. Note the time.
2. Run a clean cycle. Note the time.

**What answers it:** if `0x0C` fires with no hopper attached, it is a demand
signal; if it stays silent, it needs the hardware.

## 5. The expensive ones

**#13 / #14 — the empty cycle.** Costs a full litter refill, which is why it has
never been run. If you are changing the litter anyway, this is the moment: press
**Empty cycle (danger)** in Home Assistant (it ships disabled; enable it first) and
note the time. It confirms the captured `0x02010801` — the last unproven write on
the panel button register — and finally shows which `robotStatus` integer an empty
cycle reports, which is #14 and the reason `empty_cycle` has no local int.

**#23 — the cat weights.** If the other two cats can be weighed on a bathroom
scale the same evening, the `catWeight` divisor becomes answerable. The
known-weight method has failed three times (divisors 72.4, 84.8, 88.5, because an
inert object sheds load against the globe wall), so it needs real cats and a
same-evening household weigh-in. A single live reading on 2026-08-16 gave 707 →
7.07 lb under the shipped ÷100, which is at least a believable cat.

## 6. Standing invitation

**A cycle deferred while AWAKE**, by a bonnet lift or a full drawer, with a cat
visit inside the deferral. That is the one test that separates `0x4C` = "a cycle
is owed" from "a visit happened while asleep", and it cannot be scheduled — it
needs a cat to cooperate. If you ever notice one, note the time.

---

## What no longer needs doing

- **Panel sleep by hand** — closed 2026-08-16, `0x32` PROVEN on both robots.
- **Connect hold timing** — ~3 seconds to blinking yellow, confirmed.
- **The globe fill line** — it exists; photographed.
- **The filter** — flat carbon pad, no date tab, no mark, no indicator.
- **The device id read** — returns a MAC, so #52's auto-fill was never viable.
- **The drawer** — pulls and seats captured on both robots; the seat-only
  asymmetry is dead, and the robot does not refuse to cycle with the drawer out.
- **Power** — written and proven, both directions.
- **Connect short press** — written and proven; it toggles WiFi and turns the
  light white. Do not repeat it casually.
