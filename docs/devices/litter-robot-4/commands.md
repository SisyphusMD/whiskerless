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
| Weekday sleep enabled | `0x1D` | `0x021D000B` | 0 / 1 | yes |
| Weekday sleep/wake ×14 | `0x1E–0x2B` | `0x021E..2B VVVV` | minutes since midnight, Sunday-first — see [compatibility.md](compatibility.md#weekday-schedule) | yes |

## Actions (`0x01`, the panel button register)

`0x01` carries panel button presses, and **it accepts writes** — writing the code the
robot emits for a button synthesises that press. Live-proven on ESP 1.1.75 on
2026-08-09, three trials, no misses.

| Action | Code | Effect |
|---|---|---|
| Clean cycle | `0x02010201` | runs a full cycle — **drives the globe** |
| Panel reset | `0x02010401` | acknowledges a full alarm; aborts/resumes a paused cycle |

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
set). Power and Empty are panel buttons too, but their codes have not been
captured yet.

## Safety

whiskerless classifies every command before it can reach the wire
([`safety.py`](../../../src/whiskerless/safety.py)):

- **Never send (refused unconditionally):** `0xA3`, `0xA4` (globe-motor OTA), `0xAC`
  (main-board flash), `0xAD` (hardware reset). No flag lets these through. This is a
  cost decision rather than a proof — see
  [reverse-engineering.md](../../reverse-engineering.md); there is nothing to gain by
  sending any of them, and a plausible flash or OTA on the other side.
- **Motor (opt-in required):** the two proven panel buttons, `0x02010201` (clean
  cycle) and `0x02010401` (reset). Reset is gated too: from idle it only
  acknowledges an alarm, but mid-cycle it releases the cat-detect pause.
- **Dangerous (override required):** any untraced opcode, control-band register,
  or calibration register. Anything unrecognised defaults to "refuse unless you
  really mean it" because its effect is untested — not because a write is known to
  reach the register directly. See [protocol.md](protocol.md).
- **Safe:** reads, the report macros (value 0), and the settings above.

## What's still missing

**Power on/off and the empty cycle.** Their codes are unverified. Both are reachable
from the panel, so the `0x01` route is the obvious place to look next — the remaining
button bits are untested, and the zero-risk way to find them is to watch `0x01` while
pressing the physical button. The registers static analysis proposed are unproven and
contradict each other (three were floated for "power" alone), so nothing ships for
them yet.

The **waste-drawer reset** is not a separate command: a Reset press performs it when
the full flag is set, so it comes with `0x02010401`. That path is established but has
not yet been exercised on a genuinely full drawer.

