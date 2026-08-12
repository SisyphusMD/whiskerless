# Litter-Robot 4 — compatibility & open items

## Firmware versions

The protocol was reverse-engineered from the public **ESP 1.1.65** firmware image
and validated live against a robot running **ESP 1.1.75**, then independently
confirmed on **ESP 1.4.4** by a two-week field capture (which is also where the
LitterHopper surface came from). The wire format, the settings registers, and the
state/activity surfaces are stable across all three, and the two live builds agree
on every enum value captured on both. A few opcodes, however, **shift meaning
between firmware versions** — so re-confirm any non-settings opcode on *your*
exact build.

| Opcode | On 1.1.65 (static RE) | On 1.1.75 (live) |
|---|---|---|
| `0xA3` | reset / main-board-OTA orchestrator | reset / no-op (NOT a clean cycle) |
| `0xA0` `0xA1` `0xA7` `0xA9` `0xAE` | reports | reports (same) |
| settings `0x05`–`0x2B` | settings | settings (same) |

`0xA3` was once read as the clean-cycle trigger and *looked* like one in passing —
but a live capture proved `0x02A30000` **reboots** the robot (`odometerPowerCycles`
ticks; `odometerCleanCycles` does not); the "cycle" seen was the automatic
first-cycle-after-power-on. So `0xA3` is reset/OTA on both builds and whiskerless now
refuses it (never-send). The lesson: the safe surface (reads, reports, settings) is
consistent across versions; **action** opcodes inherited from the cloud verb map must
be confirmed live before they're trusted. Check your firmware version with the
version report (`0x02AE0000`, or the integration's *Refresh* + version sensors).

## Weekday schedule

The 14 registers `0x1E–0x2B` hold the per-weekday sleep/wake schedule as
minutes-since-midnight. On ESP 1.1.75, both the **round-trip and day ordering are
PROVEN** by writing a distinct value to every register and reading them back:
**Sunday → Saturday, sleep-then-wake per day**, i.e.

```
0x1E Sun sleep   0x1F Sun wake   0x20 Mon sleep   0x21 Mon wake   …   0x2A Sat sleep   0x2B Sat wake
```

Other firmware has not been checked. If the robot's panel shows a time on a
different day, the offset/order differs on your firmware; please
[open an issue](#open-items) with what you set and what the panel showed, and we'll
correct the mapping.

## Open items

| Action | Status |
|---|---|
| `cleanCycle` | **solved** — `0x02010201`, a synthesised panel Cycle press, three live trials |
| `shortResetPress` (panel reset) | **solved** — `0x02010401`, three live trials |
| reset waste drawer | **solved** — it is what a Reset press does when the full flag is set; not a separate command. The old "the pending-flag register is read-only, so this is impossible" note was solving the wrong problem: you write the button, not `0x41` |
| `emptyCycle` | **captured, write untested** — a physical Empty press emits `0x010801`, so `0x02010801` is the code to write. Shipped as a disabled-by-default button; nobody has sent it yet |
| `powerOn` / `powerOff` | **captured, write untested** — a Power press emits `0x010101` and TOGGLES. Shipped disabled and behind `allow_dangerous`: a robot powered off this way has left the network |
| filter-change wizard | **unreachable** — the panel chord is a *long* press, and the write path declines press type `02` |
| waste-drawer position | **partly solved** — `0x56` fires on a seat and stays silent on a removal, so direction is readable from whether it speaks; absolute position still is not. See the [register map](registers.md#the-drawer-bay-0x56-reports-seating-not-position) |

Static analysis never recovered these because it was looking in the wrong place: the
dispatch it wanted lives in a bootloader region absent from every public OTA image,
but the answer was never in the firmware at all. `0x01` is the panel button register
and it accepts writes, so the robot had been publishing each answer every time
somebody pressed a button.

Every short press was recovered the same way: capture `0x01` while pressing the
button, and the code it emits is the code to write back. What is left is not a
gap in that method but a limit of the write path — **the firmware performs short
presses and declines long ones**, so the hold-only functions (the filter wizard,
the panel's 8-hour sleep, the destructive combos) cannot be synthesised at all.
Whisker's own cloud works the same way: its complete LR4 verb list contains no
long-press command, and it reaches the hold-only *settings* by writing registers
instead, exactly as whiskerless does. The full story is in the
[reverse-engineering writeup](../../reverse-engineering.md#the-action-commands-how-the-panel-button-register-solved-all-of-them).

### The low-risk ways to chip at them

**Sniffing the cloud's own command does not work.** An earlier version of this page
suggested subscribing to your broker's `prod/LR4/<serial>/command` topic and pressing
the button in the Whisker app. That cannot work: a cloud-connected robot talks to
*Whisker's* AWS broker, not yours, so nothing appears locally. Intercepting it would
mean authenticating as the robot against Whisker's broker, which needs the factory
device key. Provisioning never touches that key, so it is out of reach without first
reading it off the ESP flash (see the
[reverse-engineering writeup](../../reverse-engineering.md)). Treat it as closed for
anyone not already doing hardware work.

What does work. Neither writes an unknown register, so neither carries brick risk;
note that pressing Cycle or Empty does move the globe, exactly as it would if you
pressed it on any other day.

**Watch the local activity stream while you press panel buttons.** A robot already on
whiskerless reports register writes as it goes. Run `whiskerless monitor`, press one
button, and note the wall-clock time so the event can be tied to the action. This is
how register `0x01` (panel button events) was found, and it is the most productive
avenue we have: it turns a physical action into a labeled wire sample.

**Pull the cloud's diagnostics for a robot still on the cloud.** Home Assistant's
`litterrobot` integration exposes the full cloud data model via *Download diagnostics*.
That gives you Whisker's field names, enum vocabulary and per-robot values, which is
how `optimalLitterLevel` and the cycle-phase names were pinned. It gives you semantics,
not the raw register write, so pair it with a local capture of the same action.

Captured something? Please share it via the **"Protocol finding"** issue template — it's
how we'll close these out. See [CONTRIBUTING.md](../../../CONTRIBUTING.md).
