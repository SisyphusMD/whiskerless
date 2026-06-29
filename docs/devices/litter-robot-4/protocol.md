# Litter-Robot 4 — wire protocol

The definitive (and, as far as we know, first public) reference for the LR4's
local MQTT protocol. Everything here is **PROVEN** on a real robot unless tagged
otherwise. See [registers.md](registers.md) for the full register map,
[commands.md](commands.md) for the actionable command catalog, and
[compatibility.md](compatibility.md) for firmware-version differences.

## Topics

The robot uses the same topic layout it used with the cloud. `<serial>` is the
unit's serial / MQTT client-id (e.g. `LR4Cxxxxxx`).

| Topic | Direction | Contents |
|---|---|---|
| `prod/LR4/<serial>/command` | you → robot | commands (the robot subscribes) |
| `prod/LR4/<serial>/state` | robot → you | full named state document |
| `prod/LR4/<serial>/activity` | robot → you | live telemetry + action echoes |

## Command payload

A command is a small JSON object published to the `command` topic:

```json
{"serial": "LR4Cxxxxxx", "data": ["0xTTRRVVVV", ...]}
```

- `serial` must equal the robot's own serial exactly, or the message is dropped.
- Each `data` element is the literal string `"0x"` followed by **exactly 8 hex
  digits** (10 characters total). Shorter elements are silently ignored, so always
  send the full width.

### The 10-character element

```
  0x T R R V V V V
     │ └┬┘ └──┬──┘
     │  │     └── 16-bit value: (HH << 8) | LL
     │  └──────── RR: register / opcode byte (0x00–0xFF)
     └─────────── T: type — 1 = READ, 2 = WRITE / macro
```

| chars | field | meaning |
|---|---|---|
| `[3]` | **T** | `1` = register READ · `2` = macro / generic register WRITE · anything else = no-op |
| `[4:6]` | **RR** | register or opcode byte |
| `[6:8]` | **HH** | value high byte |
| `[8:10]` | **LL** | value low byte |

**Value byte order (PROVEN anchor):** `0x02190064` sets night-light brightness to
`100` (`0x64`). So an 8-bit value goes in **LL** with `HH = 00`; a 16-bit value
(e.g. minutes-since-midnight, or the packed panel-brightness hi/lo pair) uses both
bytes as `(HH << 8) | LL`.

## Two control primitives

The robot's network brain exposes exactly two things:

1. **Type-1 READ** — `0x01RR0000` reads register `RR`. The robot echoes the value
   on `activity` as `0xRRVVVV`. Structurally read-only and the safest operation.
2. **Type-2 WRITE / macro** — `0x02RRVVVV`. If `RR` is one of the 9 macro opcodes
   below it runs that macro; otherwise it's a **generic write** to register `RR`.

### The 9 macros

| Opcode | Name | Effect | Safety |
|---|---|---|---|
| `0xA0` | requestState | builds the full state document → `state` | safe (read-only) |
| `0xA1` | schedule / RSSI report | sleep-wake schedule + `wifiRssi` → `activity` | safe |
| `0xA3` | reset / MB-OTA | reboots the robot or no-ops — **not** a clean cycle (live-proven) | **never send** |
| `0xA4` | globe-motor OTA | stages a motor-controller firmware flash | **never send** |
| `0xA7` | wifi-event report | wifi event → `activity` (send value `0`) | safe (value 0) |
| `0xA9` | ToF / sensor read | distance + crosstalk burst → `activity` | safe (read-only) |
| `0xAC` | main-board flash | erases/writes the main-board flash | **never send** |
| `0xAD` | hardware reset | pulses the controller's reset line | **never send** |
| `0xAE` | version report | board ids + firmware → `activity` | safe (read-only) |

> **Everything else is a generic register write.** There is **no firmware
> whitelist** — a type-2 write to any other opcode writes that PIC register
> directly. That's why whiskerless funnels every send through a
> [safety guard](commands.md#safety): the brick/reset-class opcodes above are
> refused unconditionally, and untraced writes require an explicit override.

## The activity / read-echo form

Telemetry and read echoes use a shorter `0xRRVVVV` form — register byte above a
16-bit value, no type nibble. For example `0x430052` = register `0x43`
(`DFILevelPercent`) = `0x52` = 82 %. whiskerless decodes these into named fields;
see [registers.md](registers.md).

## State document

`requestState` (`0x02A00000`) makes the robot publish a full named JSON document
on `state` — the same field names the cloud uses (`robotStatus`, `nightLightMode`,
`DFILevelPercent`, …) carrying raw integer values. whiskerless decodes the enums
to friendly strings and tolerates both the raw ints and cloud-style strings. The
field → register mapping is in [registers.md](registers.md).
