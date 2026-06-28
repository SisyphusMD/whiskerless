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
| `0x1A` | isPanelSleepMode | 0/1 | PROVEN |
| `0x1B` / `0x1C` | panelSleepTime / panelWakeTime | minutes since midnight (16-bit) | PROVEN |
| `0x1D` | weekdaySleepModeEnabled | 0/1 | PROVEN |
| `0x1E–0x2B` | weekday sleep/wake ×14 | minutes since midnight; day order [inferred](compatibility.md#weekday-schedule) | PROVEN value / inferred mapping |

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

- **robotStatus (`0x34`):** `4` = ready, `10` = cat/weight pause, `13` = cleaning
  (PROVEN). Other states (empty, find-dump, bonnet, power-up/down/off,
  cat-detect-delay) exist; their integers are LOW confidence.
- **robotCycleStatus (`0x4E`):** `1` = idle/complete, `2` = dump.
- **robotCycleState (`0x4F`):** `1` = idle; `2`/`3`/`4` = cycle progression.
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
