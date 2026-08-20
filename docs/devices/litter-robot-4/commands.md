# Litter-Robot 4 — command catalog

What you can safely tell the robot to do, and how it's encoded. The
[`whiskerless` library](../../../src/whiskerless/devices/litter_robot_4/commands.py)
builds all of these for you; this page is the reference behind it. See
[protocol.md](protocol.md) for the wire format and [registers.md](registers.md)
for the register meanings.

## Reports (safe, read-only)

| Action | Code | Result |
|---|---|---|
| Request full state | `0x02A00000` | publishes the state document |
| Wi-Fi RSSI | `0x02A10000` | `{"type": "activity", "wifiRssi": -66}` — **RSSI only**, no schedule |
| Wi-Fi event | `0x02A70000` | an empty `data` array on an idle robot (send value `0`) |
| ToF / sensors | `0x02A90000` | distance + crosstalk readings |
| Versions | `0x02AE0000` | ESP / PIC / laser-board firmware |
| Read a register | `0x01RR0000` | echoes `0xRRVVVV` |

## Settings (safe, reversible)

Encodings are PROVEN by a live read-modify-restore sweep. whiskerless writes, reads
back, and retries — but *accepting* a write is the robot's call, and the panel sleep
bank turns some of these down (see [registers.md](registers.md#the-panel-sleep-bank-is-not-a-plain-settings-bank)).

| Setting | Reg | Code | Encoding | Accepted? |
|---|---|---|---|---|
| Night-light mode | `0x18` | `0x0218000M` | 0 = off, 1 = on, 2 = auto | yes |
| Night-light brightness | `0x19` | `0x021900VV` | 0–100 % (direct) | yes |
| Clean-cycle wait time | `0x16` | `0x021600VV` | minutes | yes |
| Keypad / control lockout | `0x17` | `0x0217000B` | 0 / 1 | yes |
| Panel brightness | `0x0E` | `0x020EHHLL` | hi byte = High level, lo byte = Low level | yes |
| Panel sleep mode | `0x1A` | `0x021A000B` | 0 / 1 | no — read-only, follows `0x1D` |
| Panel sleep / wake time | `0x1B` / `0x1C` | `0x021BVVVV` | minutes since midnight (16-bit) | no — read-only view of today's weekday pair |
| Weekday sleep schedule | `0x1D` | `0x021DMMMM` | **per-day bitmask**, Sunday = bit 0. `0x7F` all days, `0x00` none — writing `1` arms Sunday alone | yes |
| Weekday sleep/wake ×14 | `0x1E–0x2B` | `0x021E..2B VVVV` | minutes since midnight, Sunday-first — see [compatibility.md](compatibility.md#weekday-schedule) | yes |

## Actions (`0x01`, the panel button register)

`0x01` carries panel button presses, and **it accepts writes** — writing the code the
robot emits for a button synthesises that press. Live-proven on ESP 1.1.75 on
2026-08-09, three trials, no misses.

| Action | Code | Effect | Evidence |
|---|---|---|---|
| Clean cycle | `0x02010201` | runs a full cycle | written, 3 trials |
| Panel reset | `0x02010401` | acknowledges a full alarm; aborts/resumes a paused cycle | written, 3 trials |
| Empty cycle | `0x02010801` | dumps the whole globe into the drawer, then parks | emission captured, **write untested** |
| Power | `0x02010101` | **toggles** the robot on or off | **written 2026-08-16**, robot powered off |
| WiFi | `0x02011001` | **toggles** the radio; light turns white | **written 2026-08-16**, robot left the broker in 0.8 s |

**Power is proven both ways.** The write produced `0x010101` on the activity stream —
the identical code the panel emits — and the physical press that brought the robot back
produced `0x010101` again, 143 seconds later. Written press and finger are the same
event, demonstrated in both directions in one capture. The shutdown is not instant: the
robot published for ~38 s after the write, walking `robotStatus` 1 → 3 with
`unitPowerStatus` (`0x31`) falling to 0, then came up 2 → 4.

**Connect (`0x02011001`) can never be verified the way the others were.** The write
performed — the robot went silent 0.8 s later and the panel light turned white — but no
echo escaped, because the press takes down the transport that would report it. The same
holds for a physical press: it happens while the radio is off and nothing replays
afterwards. `0x011001` may be permanently unobservable over MQTT in either direction, so
"the robot vanished" is the only evidence this button can ever produce.

The empty cycle is still shipped as a disabled-by-default button. Its code comes from
watching `0x01` during a physical press, which is solid, but nobody has yet written
one — and this project's own history says a captured emission is not a proven write.

The value is **`<button bits> <press type>`**. Buttons OR together, so a combo is one
write; press type is `01` short or `02` long. Bit order matches the physical panel,
left to right:

| bit | button |
|---|---|
| `0x01` | Power |
| `0x02` | Cycle |
| `0x04` | Reset |
| `0x08` | Empty |
| `0x10` | Connect |

Whisker documents every panel function in [its own support
article](https://www.litter-robot.com/support/article/litter-robot-4-control-panel-button-functions/),
which independently confirms the OR-ing: Cycle+Empty held = filter change = `0x0A`.
That article is the map of the remaining action surface — sleep mode (`0x0202`), auto
night light (`0x0402`), cycle delay (`0x0802`), panel lockout (`0x0602`), Aux1
(`0x0302`), USB power (`0x1802`).

> **Some values in this register are destructive and are refused unconditionally.**
> Reset+Empty held is a **factory reset** (`0x0C02`) — it wipes the broker
> configuration whiskerless depends on and needs a BLE re-provision to undo. Connect
> held is onboarding mode (`0x1002`), and Reset+Connect simulates a plug pull
> (`0x1402`). This is why the guard whitelists `0x01` **by value** rather than
> treating it as an open register: a factory reset is two bits from a clean cycle.
>
> Do not probe unknown bits by writing them. Press the physical button and read the
> code off the wire — that is free, and it is how Empty was recovered.

### Long presses cannot be written

**Only press type `01` is accepted as a write.** The robot happily *emits* `0x0202`
when someone holds Cycle, but writing that same value does nothing: the register
echoes `0x010000` — its resting value — and no state changes, where a short-press
write echoes the value back and acts within a second.

| written | robot answered | effect |
|---|---|---|
| `0x02010202` (Cycle long) | `0x010000` alone | none |
| `0x02010402` (Reset long) | `0x010000` alone | none, `nightLightMode` unchanged |
| `0x02010400` (Reset, type `00`) | `0x010000`, then `0x010401`, `0x350000`, `0x0B` 105 | a real Reset |

That third row is the one that settles it. An **unknown** press type is normalised to
a short press and performed, while `02` produces no event at all — so `02` is
recognised and declined, not falling through a default.

Independent corroboration from outside the robot: pylitterbot's complete
`LitterRobot4Command` list is fifteen verbs, none of them a hold, and the single
button verb is named `shortResetPress`. Whisker's own cloud cannot long-press either.
It reaches the hold-only *settings* by writing registers, exactly as whiskerless
does — lockout is `0x17`, night light `0x18`, clump time `0x16`, and the 8-hour sleep
is `0x1D` plus the `0x1E`–`0x2B` schedule.

That puts the entire long-press half of Whisker's table out of reach by this route:
sleep mode, auto night light, cycle delay, panel lockout, filter change, factory
reset. Whatever gates a long press is not expressed in this value.

It also means the destructive combos are unreachable by a write, since every one of
them is a long press. The never-send list is a second lock on a door that appears to
be shut already — kept because "appears" is doing real work in that sentence.

Each write is acknowledged the same way a settings write is, by echoing the register:

```
send 0x02010401 (idle)   -> 0x010401, 0x350000, 0x0B 105, 0x0B 22      (identical to a physical press)
send 0x02010201 (idle)   -> 0x010201, 0x0B 20, robotStatus 10, odometer +1, phases 2→3→4→5→1
send 0x02010401 (paused) -> 0x010401, 0x0B 20, cycleState 4→3           (resumed a cycle stalled 9.5 min)
```

**A written press is distinguishable from a physical one.** A write emits
`0x010000` immediately alongside the press report; a physical press emits the press
report alone. Confirmed independently on 1.1.75 and 1.4.4 across eight events, no
exceptions. (A plain *read* of `0x01` also emits `0x010000` by itself, so the
signature is the pair, not the bare value.) That makes it possible to tell an
automation-driven cycle from someone pressing the button.

This is what the five "missing actions" were blocked on. It was never a macro opcode:
the robot had been publishing the answer every time a button was pressed. Waste-drawer
reset follows from the Reset press (that is what performs it when the full flag is
set), and Power and Empty have since been captured the same way.

## Safety

whiskerless classifies every command before it can reach the wire
([`safety.py`](../../../src/whiskerless/safety.py)):

- **Never send (refused unconditionally):** `0xA3`, `0xA4` (globe-motor OTA), `0xAC`
  (main-board flash), `0xAD` (hardware reset). No flag lets these through. This is a
  cost decision rather than a proof — see
  [reverse-engineering.md](../../reverse-engineering.md); there is nothing to gain by
  sending any of them, and a plausible flash or OTA on the other side.
- **Dangerous (override required):** any untraced opcode, control-band register, or
  calibration register — and two known panel presses, `0x02010101` (Power) and
  `0x02011001` (Connect/WiFi). Anything unrecognised defaults to "refuse unless you
  really mean it" because its effect is untested, not because a write is known to
  reach the register directly. See [protocol.md](protocol.md). Power and Connect are
  the *known* commands in this class, and they are there for the opposite reason:
  every safe action can be undone over the same MQTT connection that started it,
  while a robot that is powered off — or has had its radio switched off — has left
  the network entirely.
- **Safe:** reads, the report macros (value 0), the settings above, and the routine
  panel presses (`0x0201` cycle, `0x0401` reset, `0x0801` empty).

There used to be a **Motor** class requiring `allow_motor`. It was retired: it was
invented when the globe trigger was believed to be an unknown macro opcode, and a
write to `0x01` turns out to reproduce exactly the code the panel emits, so it is the
same event as a finger on the button — the firmware's pinch, cat-detect and bonnet
interlocks sit downstream of it either way. It also protected nothing in practice,
because every caller passed the flag unconditionally.

## What's still missing

**The empty cycle still needs one live trial.** `0x02010801` is shipped disabled and
remains an inference until somebody sends it; it costs a litter refill to find out.
Power and Connect have since been written (2026-08-16) and are shipped disabled for
cost rather than for doubt — both can end with the robot off the network.

**The filter-change wizard is unreachable**, and this is a finding rather than a gap:
its chord is a long press, the write path declines those, and unlike lockout or the
night light it has no backing settings register to write instead.

The **waste-drawer reset** is not a separate command: a Reset press performs it when
the full flag is set, so it comes with `0x02010401`. Exercised on a genuinely full
drawer 2026-08-19 (1.1.75, `isDFIFull` 1 at 92 %): the press zeroed `0x42`–`0x46` and
`0x4B` within 11 s and raised `0x41`, which the next cycle's measurement cleared.

**The empty cycle's `robotStatus` integer has never been captured.** The decoder knows
the cloud string `robot_empty` but no local int, and `empty_cycle` is in the set that
suppresses litter readings — so during an empty cycle a robot may publish ToF readings
taken off a moving globe. One narrated empty cycle would close it.

