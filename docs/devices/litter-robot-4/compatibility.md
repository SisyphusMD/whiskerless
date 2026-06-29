# Litter-Robot 4 — compatibility & open items

## Firmware versions

The protocol was reverse-engineered from the public **ESP 1.1.65** firmware image
and validated live against a robot running **ESP 1.1.75**. The wire format, the
settings registers, and the state/activity surfaces are stable across both. A few
opcodes, however, **shift meaning between firmware versions** — so re-confirm any
non-settings opcode on *your* exact build.

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
minutes-since-midnight. The **round-trip is PROVEN** (writes commit and read back).
The exact **day ordering is inferred**: whiskerless assumes **Sunday → Saturday,
sleep-then-wake per day**, i.e.

```
0x1E Sun sleep   0x1F Sun wake   0x20 Mon sleep   0x21 Mon wake   …   0x2A Sat sleep   0x2B Sat wake
```

If you set a weekday time through whiskerless and the robot's panel shows it on a
different day, the offset/order is wrong for your firmware — please
[open an issue](#open-items) with what you set and what the panel showed, and we'll
correct the mapping.

## Open items

Five discrete actions are **not yet exposed** because we couldn't pin their exact
register+value safely:

| Action | Status |
|---|---|
| `cleanCycle` | unproven — the `0xA3` it was mapped to is a **reset** (live-proven), real trigger unknown |
| `powerOn` / `powerOff` | unproven — three contradictory candidate registers |
| `emptyCycle` | unproven — no cloud command string exists to cross-check |
| `shortResetPress` (panel reset) | unproven — candidate register looks like a display command |
| reset waste drawer | likely none — the pending-flag register is read-only |

The dispatch for these lives in the main board's **bootloader region**, which is
**absent from every public OTA image** (the OTA blobs are app-region only), so static
analysis can't recover them, and blind-probing the control band is exactly the kind
of write the safety guard refuses. The full hunt — including why no complete firmware
dump exists publicly and what it would take to get one — is in the
[reverse-engineering writeup](../../reverse-engineering.md#the-action-commands-why-theyre-still-missing).

### The zero-risk way to crack them

Subscribe to **your own broker's** `prod/LR4/<serial>/command` topic, then press
the button in the **Whisker app** (with the robot still on the cloud, or a second
robot). The cloud publishes the literal `{"serial","data":["0x02RRVVVV"]}` — that
hands you the register+value at PROVEN confidence with no motor or brick risk.

Captured one? Please share it via the **"Protocol finding"** issue template — it's
how we'll close these out. See [CONTRIBUTING.md](../../../CONTRIBUTING.md).
