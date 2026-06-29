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
| Schedule + RSSI | `0x02A10000` | `wifiRssi` + sleep/wake schedule |
| Wi-Fi event | `0x02A70000` | last wifi event (send value `0`) |
| ToF / sensors | `0x02A90000` | distance + crosstalk readings |
| Versions | `0x02AE0000` | ESP / PIC / laser-board firmware |
| Read a register | `0x01RR0000` | echoes `0xRRVVVV` |

## Settings (safe, reversible)

All validated by a live read-modify-restore sweep; encodings are PROVEN.
whiskerless writes, reads back, and retries (the time-of-day registers commit with
a slight delay).

| Setting | Reg | Code | Encoding |
|---|---|---|---|
| Night-light mode | `0x18` | `0x0218000M` | 0 = off, 1 = on, 2 = auto |
| Night-light brightness | `0x19` | `0x021900VV` | 0–100 % (direct) |
| Clean-cycle wait time | `0x16` | `0x021600VV` | minutes |
| Keypad / control lockout | `0x17` | `0x0217000B` | 0 / 1 |
| Panel brightness | `0x0E` | `0x020EHHLL` | hi byte = High level, lo byte = Low level |
| Panel sleep mode | `0x1A` | `0x021A000B` | 0 / 1 |
| Panel sleep / wake time | `0x1B` / `0x1C` | `0x021BVVVV` | minutes since midnight (16-bit) |
| Weekday sleep enabled | `0x1D` | `0x021D000B` | 0 / 1 |
| Weekday sleep/wake ×14 | `0x1E–0x2B` | `0x021E..2B VVVV` | minutes since midnight — see [compatibility.md](compatibility.md#weekday-schedule) |

## Safety

whiskerless classifies every command before it can reach the wire
([`safety.py`](../../../src/whiskerless/safety.py)):

- **Never send (refused unconditionally):** `0xA3` (reset / main-board-OTA
  orchestrator — proven to reboot the robot), `0xA4` (globe-motor OTA), `0xAC`
  (main-board flash), `0xAD` (hardware reset). No flag lets these through — they can
  reset or brick a controller.
- **Motor (opt-in required):** none currently. No opcode is yet proven to drive the
  globe; the gate stays in the guard for a future, confirmed cleanCycle trigger.
- **Dangerous (override required):** any untraced opcode, control-band register,
  or calibration register. The generic write has no firmware whitelist, so anything
  unrecognised defaults to "refuse unless you really mean it".
- **Safe:** reads, the report macros (value 0), and the settings above.

## What's deliberately *not* here

The clean cycle, power on/off, the empty cycle, and the panel/drawer/scale resets
are **not exposed**. We could not pin their exact register+value to safe, proven
confidence: the part of the controller firmware that dispatches those inbound
commands lives in a bootloader region **physically absent** from every public OTA
image, and the candidate registers recovered by analysis are unproven and contradict
each other (three different registers were proposed for "power" alone). The byte once
shipped as the clean cycle, `0x02A30000`, was proven on a live robot to **reset** the
unit, not run a cycle — so it's now refused, not exposed.

So they're left out — on purpose — rather than shipped unsafe. There's a clean,
**zero-risk** way to crack them (capture what the Whisker app actually sends) and a
[contribution path](compatibility.md#open-items) to do it; see the
[reverse-engineering writeup](../../reverse-engineering.md#the-action-commands-why-theyre-still-missing)
for the full hunt. Help welcome.
