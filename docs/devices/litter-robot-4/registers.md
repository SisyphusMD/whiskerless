# Litter-Robot 4 — register map

The PIC register file, as recovered from firmware and confirmed against a live
robot. One flat namespace: a register's number is the same whether you read it
(`0x01RR0000`), write it (`0x02RRVVVV`), or see it in the state document.

**R** = readable · **W** = writable (in the validated settings bank) · confidence
is **PROVEN** (live-tested), **HIGH** (firmware-decisive), or **MED/LOW**
(inference). Only the **W** rows are exposed for writing; everything else is
read/telemetry.

## Settings (read + write)

| Reg | Field | Meaning | Conf |
|---|---|---|---|
| `0x0E` | DisplayIntensity High/Low | panel brightness (hi byte = High, lo byte = Low) | PROVEN |
| `0x16` | cleanCycleWaitTime | minutes before a cycle after a cat leaves | PROVEN |
| `0x17` | isKeypadLockout | control lock 0/1 | PROVEN |
| `0x18` | nightLightMode | 0 = off, 1 = on, 2 = auto | PROVEN |
| `0x19` | nightLightBrightness | 0–100 % | PROVEN |
| `0x1A` | isPanelSleepMode | 0/1 — writable only while `0x1D` = 1, see below | PROVEN |
| `0x1B` / `0x1C` | panelSleepTime / panelWakeTime | minutes since midnight (16-bit); **read-only on ESP 1.1.75**, see below | read PROVEN / write firmware-dependent |
| `0x1D` | weekdaySleepModeEnabled | 0/1 | PROVEN |
| `0x1E–0x2B` | weekday sleep/wake ×14 | minutes since midnight; day order [inferred](compatibility.md#weekday-schedule) | PROVEN value / inferred mapping |

### The panel sleep bank is not a plain settings bank

A refused write is not silent: the robot answers every `0x02RRVVVV` with an activity
report `0xRRVVVV` carrying the register's value *after* the write. A write that took
echoes the new value (`0x02190063` → `0x190063`); a write that was refused echoes the
old one. That echo is the cheapest way to tell "rejected" from "slow to commit".

Captured on ESP 1.1.75 (`0x19` and `0x1D` accepted writes throughout, so the transport
and the settings path were both healthy):

- **`0x1A` is conditional.** With `0x1D` = 0, `0x021A0001` is refused three times over
  and echoes `0x1A0000`. With `0x1D` = 1 the identical write commits at once. The
  weekday sleep schedule is the gate on panel sleep mode.
- **`0x1B` / `0x1C` are refused outright.** Six attempts across three combinations of
  `0x1A`/`0x1D` all echoed the unchanged value, and the registers had not moved
  minutes later, so this is refusal rather than the documented commit latency.

`panelSleepTime` / `panelWakeTime` equal all seven `sleepTime<Day>` / `wakeTime<Day>`
fields on a robot with a uniform schedule, which fits them being a read-only summary
of the per-weekday registers rather than a writable setting of their own. That is
unconfirmed: it predicts `0x1E–0x2B` are the writable path, and nothing has written
them yet.

Untested on 1.4.x. The library still offers both writes, because a robot that accepts
them should keep them.

## Status & sensors (read only)

| Reg | Field | Meaning | Conf |
|---|---|---|---|
| `0x07` | unitPowerType | AC / USB / battery | HIGH |
| `0x31` | unitPowerStatus | power state | HIGH |
| `0x32` | sleepStatus | sleep state | HIGH |
| `0x34` | robotStatus | see enum below | PROVEN |
| `0x35` | globeMotorFaultStatus | 0 = none, 1..9 fault | HIGH |
| `0x37` | catDetect | cat presence | HIGH |
| `0x38` | isUSBPowerOn | USB power flag | HIGH |
| `0x39` | USBFaultStatus | 0/1/2 | HIGH |
| `0x3A` | isBonnetRemoved | bonnet interlock | HIGH |
| `0x3B` | isNightLightLEDOn | LED state | HIGH |
| `0x3D–0x40` | odometer Power/Clean/Empty/Filter cycles | lifetime counts | HIGH |
| `0x42` | DFINumberOfCycles | drawer cycles | HIGH |
| `0x43` | DFILevelPercent | waste drawer % full | PROVEN |
| `0x44` / `0x4B` | isDFIFull / isDFIPartialFull | drawer full / partial | HIGH |
| `0x47` | litterLevel | litter distance in mm | PROVEN |
| `0x4D` | globeMotorRetractFaultStatus | fault enum | HIGH |
| `0x4E` | robotCycleStatus | 1 = idle, 2 = dump | HIGH |
| `0x4F` | robotCycleState | 1 = idle, 2→3→4 progression | HIGH |
| `0x58–0x5A` | ToF1/2/3 | distance sources | PROVEN |
| `0x09` | catWeight | raw / 100 = lb (telemetry) | HIGH |

## Enums

The firmware emits raw integers; whiskerless decodes them (and tolerates the
cloud-style strings, too). Values tagged PROVEN are confirmed live; others are
named but their exact integers aren't all pinned yet.

- **robotStatus (`0x34`):** `4` = ready, `10` = **clean cycle in progress**, `5` =
  bonnet removed, `6`/`7` = post-visit countdown, `25` = cat detected / weight on
  the scale. `4` and `10` are live-captured on both ESP 1.1.75 and 1.4.4; the rest
  on 1.4.4 only. There is no firmware split — the two builds agree on every value
  either has been seen to emit.
  This table previously read `10` = cat/weight pause and `13` = cleaning, tagged
  PROVEN. That came from a static firmware-RE brief and was never checked against
  a live cycle. A narrated manual cycle on 1.1.75 holds `robotStatus` at `10` for
  the entire cycle with `catDetect` at `0` throughout, and `13` has never appeared
  on either firmware. Other cloud-string states (empty, find-dump, power-up/down,
  filter-change) exist; their integers remain unpinned.
- **robotCycleStatus (`0x4E`):** `1` = idle/complete, then `2` → `3` → `4` → `5` → `1`
  per cycle. The cloud names them DUMP → DFI → LEVEL → HOME → IDLE; the drawer is
  measured during `3` and the LitterHopper dispenses during `4`. Captured on both
  1.1.75 and 1.4.4.
- **robotCycleState (`0x4F`):** `1` = idle; `2`/`3` = cycle progression with
  transient `12`/`15` excursions; **`4` = the mid-cycle cat-interrupt pause**. The
  pause is visible only here — `robotStatus` stays at `10` (cleaning) throughout —
  and it self-clears when the cat leaves, resuming without any button press
  (owner-witnessed on both firmwares).
- **nightLightMode (`0x18`):** `0` = off, `1` = on, `2` = auto (PROVEN).
- **nightLightBrightness (`0x19`):** direct %, common presets 25 / 50 / 100.
- **globeMotorFault / Retract (`0x35` / `0x4D`):** `0` = none, `1..9` = fault.
- **catWeight:** raw int16 ÷ 100 = pounds.

## A note on the state document

The local `state` document uses the cloud's field **names** (e.g. `robotStatus`)
with raw integer **values**. whiskerless maps each named field back to its
register and decodes it; if your robot turns out to emit a string where this table
expects an int (or vice-versa), the decoder handles both. If you spot a mismatch,
please [report it](compatibility.md#open-items).
