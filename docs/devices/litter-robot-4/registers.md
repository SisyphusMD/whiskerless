# Litter-Robot 4 — register map

The PIC register file, as recovered from firmware and confirmed against a live
robot. One flat namespace: a register's number is the same whether you read it
(`0x01RR0000`), write it (`0x02RRVVVV`), or see it in the state document.

**R** = readable · **W** = writable (in the validated settings bank) · confidence
is **PROVEN** (live-tested), **HIGH** (firmware-decisive), or **MED/LOW**
(inference). Only the **W** rows are exposed for writing; everything else is
read/telemetry.

**What PROVEN has to mean here.** For a writable register: a write was observed to
change the value *and* the new value observed coming back. For a read register: the
value was observed moving in step with a physical event. `0x1A` passed every weaker
test — it was readable, it decoded, its name matched the setting, and a write even
appeared to succeed — and it is still not writable. A tag inherited from the static
firmware brief is an inference, not a test, and has already been wrong twice
(`robotStatus` `13`; the panel sleep bank).

Observations that have not yet earned a row here — a register seen firing once, a
value pattern from a single cycle — accumulate in
[`capture-notebook.md`](capture-notebook.md) until a later capture reproduces them.

## Settings (read + write)

| Reg | Field | Meaning | Conf |
|---|---|---|---|
| `0x0E` | DisplayIntensity High/Low | panel brightness (hi byte = High, lo byte = Low) | PROVEN |
| `0x16` | cleanCycleWaitTime | minutes the robot waits before cycling | PROVEN |
| `0x17` | isKeypadLockout | control lock 0/1 | PROVEN |
| `0x18` | nightLightMode | 0 = off, 1 = on, 2 = auto | PROVEN |
| `0x19` | nightLightBrightness | 0–100 % | PROVEN |
| `0x1A` | isPanelSleepMode | 0/1 — **read-only**, follows `0x1D`, see below | PROVEN |
| `0x1B` / `0x1C` | panelSleepTime / panelWakeTime | minutes since midnight (16-bit); **read-only**, mirrors today's weekday pair | PROVEN |
| `0x1D` | weekdaySleepModeEnabled | **per-day bitmask**, bit *i* = `WEEKDAYS[i]` Sunday-first; `0x7F` = every day | PROVEN |
| `0x1E–0x2B` | weekday sleep/wake ×14 | minutes since midnight, `0x1E + 2i` / `0x1F + 2i` Sunday-first | PROVEN, mapping included |

### The panel sleep bank is not a plain settings bank

A refused write is not silent: the robot answers every `0x02RRVVVV` with an activity
report `0xRRVVVV` carrying the register's value *after* the write. A write that took
echoes the new value (`0x02190063` → `0x190063`); a write that was refused echoes the
old one. That echo is the cheapest way to tell "rejected" from "slow to commit".

Captured on ESP 1.1.75 (`0x19` and `0x1D` accepted writes throughout, so the transport
and the settings path were both healthy). **Three of these registers are computed by
the firmware, not stored** — writing them is accepted and discarded:

- **`0x1A` tracks `0x1D`.** Toggling `weekdaySleepModeEnabled` alone, with no `0x1A`
  write at all, moved `isPanelSleepMode` with it in both directions. A direct write is
  refused and echoes the register unchanged; an earlier apparent success was only the
  verify predicate matching a value `0x1D` had already changed.
- **`0x1B` / `0x1C` mirror *today's* weekday pair.** Writing `0x1F` (Sunday wake) to
  905 on a Sunday moved `wakeTimeSunday` to 905 *and* `panelWakeTime` with it, while
  `wakeTimeMonday` stayed at 920. Six direct writes across three combinations of
  `0x1A`/`0x1D` all echoed unchanged.

`0x1D` is a **bitmask, not a flag** — bit *i* arms the schedule for the same day as
the `0x1E + 2i` pair. The panel's own 8-hour sleep writes `0x7F`, which is how the
shape surfaced; writing `1` arms Sunday only, and looks like it worked if you happen
to test on a Sunday.

So the writable surface is `0x1D` (which days) and `0x1E–0x2B` (the schedule). Setting a
unified sleep or wake time means writing all seven of that side's registers.

The day order is no longer inferred. Writing a **distinct** value to each of the seven
sleep registers in one pass and reading the document back identified every one:
`0x1E + 2i` / `0x1F + 2i`, Sunday-first, exactly as assumed. That pass also showed why
each register must be verified individually — one of the seven (`0x26`) silently did
not take, while the other six did, and an identical retry landed it. Verifying only
`0x1B` would have reported success: it mirrors *today*, and today's register was one
of the six that worked.

Only 1.1.75 has been tested, but this is a data model rather than a behaviour, so a
1.4.x difference would be surprising. The `PROVEN` these rows once carried appears to
have been inherited from the static firmware brief, the same way `robotStatus` `13`
was.

## Status & sensors (read only)

| Reg | Field | Meaning | Conf |
|---|---|---|---|
| `0x07` | unitPowerType | **`0` = mains, `1` = battery** — proven by pulling AC and restoring it | PROVEN |
| `0x31` | unitPowerStatus | `1` on a running robot; unchanged across a mains→battery→mains transition | LOW |
| `0x38` | isUSBPowerOn | **mains present, not USB** — went 1→0 with AC out and back, with the hopper untouched throughout. The LR4 has no user USB power; the field is misnamed | PROVEN |
| `0x32` | sleepStatus | `1` while inside the panel sleep window, `0` outside — tracks the clock, not just the enable bit. The *field* is live-proven (both boundary transitions captured against the schedule); the register number rests on the brief plus one capture's two aligned `0x32` activity transitions | PROVEN (field) |
| `0x34` | robotStatus | see enum below | PROVEN |
| `0x35` | globeMotorFaultStatus | 0 = none, 1..9 fault | HIGH |
| `0x37` | catDetect | **not a boolean** — the state doc shows 0–3, and two robots on one firmware use different vocabularies (`3` vs `1` for a cat; see the [notebook](capture-notebook.md)). Activity carries 16/17/32/33 — cat-correlated — plus 256, and 512/1024 on bonnet open/close | LOW |
| `0x39` | USBFaultStatus | 0/1/2 | HIGH |
| `0x3A` | isBonnetRemoved | bonnet interlock | HIGH |
| `0x3B` | isNightLightLEDOn | LED state | HIGH |
| `0x3D–0x40` | odometer Power/Clean/Empty/Filter cycles | lifetime counts | HIGH |
| `0x42` | DFINumberOfCycles | drawer cycles | HIGH |
| `0x43` | DFILevelPercent | waste drawer % full | PROVEN |
| `0x44` / `0x4B` | isDFIFull / isDFIPartialFull | drawer full / partial | HIGH |
| `0x47` | litterLevel | litter distance in mm | PROVEN |
| `0x4D` | globeMotorRetractFaultStatus | fault enum | HIGH |
| `0x4E` | robotCycleStatus | `1` = idle, then `2`→`3`→`4`→`5`→`1` — see enum | PROVEN |
| `0x4F` | robotCycleState | `1` = idle; `4` = cat-interrupt pause — see enum | PROVEN |
| `0x56` | drawer bay | the waste drawer **moved** — direction is not recoverable, see below | PROVEN (as an event) |
| `0x58–0x5A` | ToF1/2/3 | distance sources | PROVEN |
| `0x09` | catWeight | raw / **100** = lb (telemetry) — see the enum note | MED |

## Enums

The firmware emits raw integers; whiskerless decodes them (and tolerates the
cloud-style strings, too). Values tagged PROVEN are confirmed live; others are
named but their exact integers aren't all pinned yet.

- **robotStatus (`0x34`):** `4` = ready, `10` = **clean cycle in progress**, `5` =
  bonnet removed, `6`/`7` = post-visit countdown, `25` = cat detected / weight on
  the scale. `4`, `10`, `7` and `25` are live-captured on both ESP 1.1.75 and 1.4.4
  (`6` too, but on 1.1.75 only via `0x340006` on the activity stream — no state
  document has caught it); `5` on 1.4.4 only. There is no firmware split — the two
  builds agree on every value either has been seen to emit.
  Also live-captured since: `1`/`2`/`3` during power-up (which of the three means
  what is unresolved, so they share one slug), **`13` = the automatic cycle a robot
  runs on boot**, and **`14` = the filter-change wizard**. Both 13 and 14 suppress
  litter readings — 13 turns the globe, 14 parks it inverted for minutes.

  This table previously read `10` = cat/weight pause and `13` = cleaning, tagged
  PROVEN, from a static firmware-RE brief never checked against a live cycle. A
  narrated manual cycle on 1.1.75 holds `robotStatus` at `10` throughout with
  `catDetect` at `0`, so `10` is the clean cycle. `13` was then removed from the
  map for lack of any observation, and later captured on a power cycle — so the
  brief was half right about it: cycling, but not the *clean* cycle.
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
- **catWeight (`0x09`):** raw int16 ÷ **100** = pounds, matching the cloud
  field's units. The divisor spent a few days at 50 on the strength of one
  reading — raw 408 attributed to a cat weighing ~8.1 lb on a household scale —
  until a 23h37m capture produced seven distinct raws (666–1095) that ÷50 turns
  into 13.3–21.9 lb, double every cat in the household (owner-attributed range
  ~8–12 lb), while ÷100 gives 6.7–11.0 lb and reads raw 809 as 8.09 lb —
  matching the same cat's weigh-in exactly. The lone 408 (≈ half of 809) is the
  unexplained reading, not the units. A narrated visit — known cat, noted time,
  raw read off the wire — is still what would close this for good.

## The drawer bay (`0x56`) reports movement, not position — an open problem

This is the weakest decode in the map, and it is documented as unsolved rather than
patched again. **What is solid:** `0x56` is silent unless the waste drawer moves, and
the state document's DFI fields never flag a pulled drawer, so this register is the
only drawer-service signal there is.

**What is not:** which way it moved. Across three rounds of narrated pulls the values
were 10, 11, 13, 14, 15, 16, 17 and 28, with removals and insertions sharing values;
seating the drawer fully sometimes emitted nothing at all. A direct type-1 read
answers ~78 whether the drawer is in **or** out, so position cannot be recovered that
way either.

Three successive attempts to name a removal code each held until the next capture
contradicted them (`{10}`, then `{10, 11}`, then a per-unit theory that was wrong).
whiskerless therefore exposes *when the drawer last moved* and claims nothing about
where it is.

**What would actually settle it.** Not more pulls — a *timestamped, narrated* sequence
recorded against a running capture, where every transition is called out as it
happens: out, in, out, half, in, and a full seat, with the wall-clock of each. Every
prior attempt failed because the pulls were recounted afterwards and the codes could
not be matched to specific movements. Two candidate models are worth testing against
such a capture: that the value is a duration or a travel measurement rather than a
state code, and that the low nibble carries the direction while the rest is noise.
Until a capture can distinguish those, a boolean here is a guess.

## A note on the state document

The local `state` document uses the cloud's field **names** (e.g. `robotStatus`)
with raw integer **values**. whiskerless maps each named field back to its
register and decodes it; if your robot turns out to emit a string where this table
expects an int (or vice-versa), the decoder handles both. If you spot a mismatch,
please [report it](compatibility.md#open-items).


## The register file is `0x00`–`0x7F`

A full sweep — a type-1 read of all 256 addresses, paced 3 s apart — answered on
**123 of the 128 addresses at or below `0x7F` and on none at all above it**. So the
readable file is 7-bit. `0xBC` (cat visit duration) and the `0xA0`–`0xAE` macros never
answer a read: they are a separate namespace, not entries in this file.

The only gap inside the low range is `0x6A`–`0x6E`, five contiguous addresses.

**Pacing is not optional, and a silent register proves nothing on its own.** The same
sweep at 1 s spacing answered about a tenth as often, and a burst answered 30 and then
stopped; hand-paced reads at ~3 s answered 5 of 5. Registers we had already *written*
to went silent under tight pacing. Any claim that an address is unimplemented needs a
properly paced sweep, ideally twice.

### Identified by matching the sweep against the state document

| Reg | Value read | Field |
|---|---|---|
| `0x79` | 41027 | `mbRevisionId` |
| `0x7A` | 29856 | `mbDeviceId` |
| `0x7F` | 10500 | `mbHardware` |

`0x73`–`0x7F` looks like a board identity block; `0x7E` read 5, which matches three
different state fields, so it stays unassigned rather than guessed.

### Answering but unidentified

`0x0B` (22/102 — the marker byte seen constantly in activity), `0x10`–`0x15`,
`0x2C`, `0x2F`, `0x30`, `0x33`, `0x48`–`0x4A` (the three drawer lasers), `0x50`–`0x55`,
`0x5E`, `0x64`, `0x73`–`0x77`, `0x7B`.

`0x10`–`0x12` **changed value between passes**, so they are live counters rather than
configuration. `0x50` read 129 during a power-source switch and 146 later, and it is
the only register that appeared in the mains→battery transition burst — a battery
reading is the obvious guess and is not yet evidence.

A further 33 answer but read zero, which says nothing about their meaning.

`0x3C` and `0x66` are two of those zeroes, and they are the concrete reason a zero says
nothing: both were later caught emitting on the activity stream during a clean cycle,
where they carry values that repeat cycle to cycle — see the
[capture notebook](capture-notebook.md).

### What the sweep cannot tell you

Values only. Nothing is labelled, so meaning comes from cross-matching the named
state document, perturbing something physical and re-reading, or recognising the
shape of a value (`0x0E` reads 23140 = `0x5A64` = the 90/100 brightness pair). A
register reading zero on an idle robot is simply uninformative.
