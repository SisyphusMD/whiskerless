# Litter-Robot 4 — compatibility & open items

## Firmware versions

The protocol was reverse-engineered from the public **ESP 1.1.65** firmware image
and validated live against a robot running **ESP 1.1.75**. The wire format, the
settings registers, and the state/activity surfaces are stable across both. A few
opcodes, however, **shift meaning between firmware versions** — so re-confirm any
non-settings opcode on *your* exact build.

| Opcode | On 1.1.65 (static RE) | On 1.1.75 (live) |
|---|---|---|
| `0xA3` | main-board OTA orchestrator | **real clean cycle** |
| `0xA0` `0xA1` `0xA7` `0xA9` `0xAE` | reports | reports (same) |
| settings `0x05`–`0x2B` | settings | settings (same) |

The lesson: the safe surface (reads, reports, settings) is consistent; the
**action** opcodes are the ones that move between versions. whiskerless treats
`0xA3` as a motor command and gates it accordingly. Check your firmware version
with the version report (`0x02AE0000`, or the integration's *Refresh* + version
sensors) before relying on any action opcode.

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

Four discrete actions are **not yet exposed** because we couldn't pin their exact
register+value safely:

| Action | Status |
|---|---|
| `powerOn` / `powerOff` | unproven — three contradictory candidate registers |
| `emptyCycle` | unproven — no cloud command string exists to cross-check |
| `shortResetPress` (panel reset) | unproven — candidate register looks like a display command |
| reset waste drawer | likely none — the pending-flag register is read-only |

The handler for these lives in a part of the controller firmware that is
**physically truncated out of the public image**, so static analysis can't recover
them, and blind-probing the control band is exactly the kind of write the safety
guard refuses.

### The zero-risk way to crack them

Subscribe to **your own broker's** `prod/LR4/<serial>/command` topic, then press
the button in the **Whisker app** (with the robot still on the cloud, or a second
robot). The cloud publishes the literal `{"serial","data":["0x02RRVVVV"]}` — that
hands you the register+value at PROVEN confidence with no motor or brick risk.

Captured one? Please share it via the **"Protocol finding"** issue template — it's
how we'll close these out. See [CONTRIBUTING.md](../../../CONTRIBUTING.md).
