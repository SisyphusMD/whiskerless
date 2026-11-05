# Litter-Robot EVO — wire protocol

Reference for the Litter-Robot EVO's local MQTT protocol (cloud model type `LRE`).
The EVO shares the LR4's provisioning channel and MQTT envelope but not its
register map, and it has no state document: state is read register by register.
The library implements it in
[`devices/litter_robot_evo`](../../../src/whiskerless/devices/litter_robot_evo/),
and the CLI drives it with `whiskerless evo`.

Confidence tags:

- **PROVEN** — the robot echoed the write, or the value lined up with the field Whisker's
  cloud reported for the same moment.
- **INFERRED** — consistent with every reading, but not directly confirmed.
- **OPEN** — reported by the robot, meaning not known.

## Using it

```bash
whiskerless provision --serial LRE-01-40-01-2610-000000   # setup mode first, see below
whiskerless evo monitor                                    # watch what the robot reports
whiskerless evo brightness 1 1                             # screen and status LED to 1
whiskerless evo sleep --days saturday sunday --sleep 22:00 --wake 07:00
whiskerless evo set-clock                                  # the robot's clock to local time
```

Provisioning writes the EVO's own topic prefix, `prod/robots`, so a robot moved
between Whisker's cloud and a local broker keeps the same topics. A robot
provisioned under another prefix is driven with `--topic-prefix`.

## Hardware and firmware

| Item | Value |
|---|---|
| Cloud model type | `LRE` (pylitterbot treats it as a `LitterRobot5`, unmapped model name) |
| Robot (main-board) firmware | `v4.7.0 2904_104` — `2904` is an LR4-family board id |
| IoT (ESP) firmware | `v2.6.4` |
| MQTT client | AWS IoT Embedded C SDK; username `?SDK=C&Version=3.0.1` |
| Panel | LCD screen plus one RGB status LED; no night light, no ambient light sensor |
| Cat detection | weight; a hand in the globe registers nothing |

## Provisioning (BLE)

Same ESP-IDF protocomm design as the LR4, under a different service UUID and name.

| Item | Value |
|---|---|
| Advertised name | `LitterRobotEvo` |
| Service UUID | `28cbfd44-6c8c-43c4-88ee-4da18ca98510` |
| Characteristics | `28cb000N-6c8c-43c4-88ee-4da18ca98510`, labelled by `0x2901` descriptors |
| Endpoints | `0001` prov-session, `0002` prov-config, `0003` proto-ver, `0004` prov-scan, `0005` mqtt-config, `0006` whisker-config |
| Security | `proto-ver` reports `no_sec,no_pop,wifi_scan` — every write, including the device private key, is cleartext |
| Advertising | in setup mode (light breathing blue); not reliably while connected, so provisioning needs setup mode |

The `mqtt-config` and `whisker-config` messages match the LR4 schemas
(`whisker_mqtt_config.proto`, `whisker_config.proto`) field for field. **PROVEN**:
whiskerless provisions an EVO with the same flow as an LR4.

What the Whisker app writes during onboarding (**PROVEN**). Provisioning with
whiskerless writes the same endpoints for an EVO, pointed at your broker:

| Write | Value |
|---|---|
| Device id | the serial, `LRE-` followed by hyphenated hex groups (`LRE-01-40-01-2610-000000`) |
| Host | `a2wz9c6y6mikoy-ats.iot.us-east-1.amazonaws.com` (the LR4's endpoint too) |
| Cloud endpoint (subscribe) | `prod/robots/<serial>/command` |
| Device endpoint (publish) | `prod/robots/<serial>/activity` |
| Certificates | Amazon Root CA 1, an AWS IoT device certificate, its RSA key |

The robot publishes on topics that share the device endpoint's prefix: `activity`,
`event`, and, in the LR4 layout, `state`. Provisioned with `prod/LR4/<serial>/…`
endpoints, it uses `prod/LR4/<serial>/event` as well. Port 8883 is fixed.

## Command envelope

Published to the command topic:

```json
{"serial": "<serial>", "data": ["0xTTBBRRVVVV", ...]}
```

Each element is `0x` and 10 hex digits: type, bank, register, 16-bit value.

| Field | Meaning |
|---|---|
| `TT` | `01` read, `02` write |
| `BB` | bank: `01` robot / actions, `02` settings; `05` and `08` appear only in telemetry |
| `RR` | register within the bank |
| `VVVV` | value, big-endian |

**PROVEN**. The cloud sends several elements in one message when a setting spans
registers (the sleep schedule).

LR4-style 8-digit elements (`0xTRRVVVV`) are misparsed, not ignored: the robot
acknowledges them at the wrong address and acts on nothing.

## Replies and telemetry

The robot publishes on `activity`:

```json
{"timestamp": "…", "type": "activity", "data": ["0xBBRRVVVV", ...]}
```

Elements drop the type byte: `0xBBRRVVVV`.

- **Write echo** (**PROVEN**): an accepted write comes back on `activity` as
  `0xBBRRVVVV` with the value the robot applied. That value can differ from the one
  written; see panel brightness.
- **Read replies** (**PROVEN**): `type` is `query`, with one element per register
  read, in request order, each carrying the register's current value. Registers
  that cannot be read answer with `0000`; see [Reading state](#reading-state).
- **Unsolicited telemetry** (**PROVEN**): changes in robot state arrive on
  `activity` without a request.

## There is no state document

None of the LR4 report macros produce data on the EVO. `0x02A00000` (requestState),
`0x02A10000`, `0x02A70000`, `0x02A90000` and `0x02AE0000` are each acknowledged as
`0xA?000000` and nothing more. **PROVEN**.

State is read register by register instead, and kept current from telemetry and
echoes.

## Reading state

A read is a 12-character element with type `01`: `0x01BBRR0000` (the value is
ignored). Several reads go in one command message, and the robot answers with one
`query` message holding one element per read, in request order. **PROVEN**:

```json
{"serial": "<serial>", "data": ["0x0101030000", "0x0102090000", "0x0102010000"]}
{"timestamp": "…", "type": "query", "data": ["0x01030004", "0x02090007", "0x02010808"]}
```

Most registers answer with their current value. The rest answer with `0000`
whatever they hold, so they are known only from telemetry. **PROVEN**:

| Bank | Readable | Answers `0000` |
|---|---|---|
| `01` | `03` status, `05` power-cycle odometer, `06`, `07` empty-cycle odometer, `08`, `0A` cycle step, `0B` cycle phase, `14` power, `16`, `18` bonnet, `20` drawer, `22` | `01` button, `02` display code, `04`, `09` |
| `02` | `01` panel brightness, `09` cycle delay, `0A` lockout, `0F`, `10` sleep days, `11`–`1E` sleep and wake times | — |
| `03` | — | `05`, `06` (usage elements, sent only in events) |
| `05` | `14` | `0A`–`0C` drawer counters, `1B` weight, `22`–`26` motor readings |
| `06` | `0A` | — |
| `08` | — | `0A`, `12` |
| `09` | `08` (main-board id) | — |

Bank 01 `16`, bank 02 `0F` and bank 06 `0A` answer with non-zero values; their
meanings are **OPEN**.

An 8-character LR4-style read is misparsed like any other LR4 element, and a read
of an address the robot does not implement also answers `0000`.

On every connect, the cloud pushes its stored settings, for example panel brightness as
`0x0202010808`. A local driver that wants its own values to stick must reapply them
after each reconnect. **PROVEN**. The full sequence is under
[Reconnect resync](#reconnect-resync).

## Settings — bank 02

| Register | Setting | Encoding | Status |
|---|---|---|---|
| `01` | panel brightness | high byte screen, low byte status LED, 1–100 each. App presets: Low `0808`, Medium `1414`, High `2828`. A byte of 0 is replaced with 50 (`0x32`) | PROVEN |
| `02`–`08` | the robot's clock, in local time | `02` weekday (0 = Sunday), `03` hour, `04` minute, `05` second, `06` day of the month, `07` month, `08` year in two digits (`1A` = 2026). The sleep schedule runs on this clock | PROVEN (weekday base INFERRED) |
| `09` | cycle delay | minutes | PROVEN |
| `0A` | control panel lockout | 0 / 1 | PROVEN |
| `10` | sleep schedule days | bitmask, bit 0 = Sunday … bit 6 = Saturday; `0041` = weekends | PROVEN |
| `11`–`1E` | sleep / wake times | minutes after midnight, Sunday first, sleep then wake: `11` Sun sleep, `12` Sun wake, … `1D` Sat sleep, `1E` Sat wake | PROVEN |

The cloud writes a sleep schedule as all fifteen registers in one message, with the
day mask last. It writes the clock as all seven registers in one message, in
register order, each time the robot connects; `commands.set_clock` builds the same
message for a robot without the cloud.

After a settings write, the display code (`0102`) shows `32` or `33`, the panel's
setting-updated screen, then returns to idle.

## Actions — bank 01

| Command | Action | Robot's report | Status |
|---|---|---|---|
| `0x020103000A` | clean cycle | `0103000A`, then cycle telemetry | PROVEN |
| `0x020103000B` | empty cycle: dumps the globe into the drawer, then **waits at the dump position for a Cycle press** | `0103000B`, cycle step `0006`, odometer `0107` + 1 | PROVEN |
| `0x020103000C` | change filter: rotates the globe for bonnet access | `0103000E` | PROVEN |
| `0x0201220001` | reset drawer level | `01220000`; `050A`, `050B`, `050C` → 0 | PROVEN |
| `0x0201140000` | power off | `01140000`, status `03` | PROVEN |
| `0x0201140001` | power on | `01140001`, odometer `0105` + 1, status `02` → `04`, display `67` → `16` | PROVEN |
| remote reset | clears faults | — | OPEN |

The clean cycle, empty cycle and filter change are each a write of the robot
status the robot then reports. The Whisker app does not offer the empty cycle;
the panel starts it with a Cycle hold, and the status write starts the same cycle.

**An empty cycle does not finish on its own.** After the dump the globe stops at
the dump position until Cycle is pressed on the panel (`01010201`); it then
returns home with cycle step `0007`, which the cloud labels `StCycleEmptyHome`.
Panel-press writes are untested, so the driver offers no command for that press:
a written empty cycle needs a person at the robot to send the globe home.

After the change-filter rotation, the robot waits for the bonnet to come off and go
back on, then for a Connect press (`01010801`), and then returns home.

The robot stays connected to the broker while powered off and accepts power on.
Around a power change it repeats some telemetry two or three times in a row; the
repeats carry the same values, and folding them into state changes nothing.

## Telemetry registers

### Bank 01

| Register | Meaning | Values | Status |
|---|---|---|---|
| `01` | button press: high byte the button (`02` Cycle, `04` Cancel, `08` Connect), low byte the press (`01` short, `02` held about 3 s) | see the button table below | PROVEN |
| `02` | display code | see the table below | PROVEN |
| `03` | robot status | `02` powering up, `03` powering down, `04` ready, `0A` cleaning, `0B` emptying, `0E` changing filter; `06` and `07` around a weight event (OPEN) | PROVEN |
| `04` | — | `0020`, `0021` around drawer and weight events; `0100` after the weight sensors are zeroed | OPEN |
| `05` | power-cycle odometer, reported at each power-on; the cloud's `odometerPowerCycles` | count | PROVEN |
| `06` | — | `0004` in the cycle-complete event | OPEN |
| `07` | empty-cycle odometer; the cloud's `odometerEmptyCycles` | count | PROVEN |
| `08` | — | `0002` at the start of a filter change | OPEN |
| `09` | — | `0004` at the end of a cycle | OPEN |
| `0A` | cycle step | `01`–`05` during a clean cycle; `06` during an empty cycle, `07` for its return home; `0E`, `0F` during a filter change | INFERRED |
| `0B` | cycle phase marker | `02`, `03` at each step, `0C` before motor readings, `01` at the end | INFERRED |
| `14` | power | 1 on, 0 off | PROVEN |
| `18` | bonnet removed | 1 / 0 | PROVEN |
| `20` | drawer removed | 1 / 0; toggles 1 → 0 → 1 → 0 within a few seconds while the drawer is being seated, so debounce it before acting | PROVEN |
| `22` | drawer-level reset | write 1 to reset | PROVEN |

Button codes (`0101`):

| Code | Button and press | Effect | Status |
|---|---|---|---|
| `0201` | Cycle, short | starts a clean cycle; resumes a paused cycle; sends a paused empty cycle home | PROVEN |
| `0202` | Cycle, held | starts an empty cycle | PROVEN |
| `0401` | Cancel, short | at home with the light solid white, zeroes the weight sensors; dismisses resettable alerts | PROVEN |
| `0402` | Cancel, held | starts the filter-change rotation (from the EVO manual) | INFERRED |
| `0801` | Connect, short | confirms the filter-change step | PROVEN |

Display codes (`0102`), each matched to the cloud's `displayCode`:

| Value | Cloud name / meaning |
|---|---|
| `00` | after a drawer-level reset (OPEN) |
| `06` | `DcBdDrawer` — drawer removed |
| `07` | `DcBonnetOff` |
| `09` | `DcCatDetect` |
| `0C` | `DcUserPause` (also during a filter change) |
| `14` | `DcModeCycle` |
| `16` | `DcModeIdle` |
| `26` | `DcWifiStatus` |
| `32`, `33` | setting updated |
| `66`, `67` | connecting / powering up |
| `69` | weight sensors zeroed (INFERRED) |
| `6A` | `DcxLockoutKeyhit` — button pressed while locked |

### Bank 05

| Register | Meaning | Status |
|---|---|---|
| `0A` | drawer fullness counter; reported in cycle events, zeroed by the drawer reset | INFERRED (cloud `dfiLevelPercent`) |
| `0B`, `0C` | drawer counters, zeroed by the drawer reset | OPEN |
| `14` | — `0094` around power changes | OPEN |
| `1B` | weight sensor, signed 16-bit (`FFD6` = −42) | INFERRED; scale OPEN |
| `22`–`26` | motor and position readings, one burst per cycle step; `24` and `26` carry the step in their high nibble | OPEN |

### Bank 08

| Register | Meaning | Status |
|---|---|---|
| `0A` | `0000` at the start of every cycle | OPEN |
| `12` | 1 while a weight measurement settles, then 0 | INFERRED |

### Bank 09

| Register | Meaning | Status |
|---|---|---|
| `08` | reads `2904`, the main-board id in the robot firmware string (`2904_…`); emits several other values while an empty cycle dumps the globe | INFERRED (id) / OPEN (cycle values) |

## The event topic

`event` carries records with a `type` and a `uuid`:

| `type` | Data | Notes |
|---|---|---|
| `cycle` | e.g. `0x01030004 0x050A000F 0x050B0000 0x01060004` | sent when a cycle completes |
| `usage` | e.g. `0x01030004 0x03050030 0x03060373`, plus `"pawprint": […]` | weight events, including the drawer being reseated |

Event elements use bank `03`:

| Element | Meaning | Status |
|---|---|---|
| `0306VVVV` | weight in hundredths of a pound (`0373` = 8.83 lb), the cloud's `weightSensor` | PROVEN |
| `0305VVVV` | — | OPEN |

## JSON messages

Alongside hex elements, the robot and cloud exchange typed JSON messages, each wrapped in
a `pawprint` envelope whose `data` holds one object. **PROVEN**.

| Direction | `data[0]` | Purpose |
|---|---|---|
| robot → `activity` (with `uuid`) | `{"type": "pet_profile_request"}` | sent after power-on |
| cloud → `command` (with `serial`) | `{"type": "pet_profile", "md5": …, "pet_profiles": [{"id": "PET-…", "weight": …}, …]}` | the account's pets, for on-robot pet identification |
| cloud → `command` (with `serial`) | `{"type": "wplus_subscription"}` | subscription status |
| robot → `activity` | `{"type": "pet_id_match", "profile": "PET-…", "confidence": …, "sources": […]}` | the pet the robot matched a weight to, from the profiles the cloud sent, with its confidence |

A cloud-free driver must answer `pet_profile_request` itself if the robot is to
identify pets.

Marking a weight event as a litter refill in the Whisker app happens in the cloud
only: nothing is sent to the robot, and the robot's own `usage` event and
`pet_id_match` stand. A local driver needs its own way to reclassify a refill.

## Reconnect resync

When the robot connects, after a power-on (which it announces with
`pet_profile_request`) or a network drop, Whisker's cloud brings it up to date in a
fixed order. **PROVEN**:

1. Reads bank 09 register `0A`.
2. Sets the clock: bank 02 registers `02`–`08` in one message.
3. Reads three multi-element batches: the settings bank (brightness, cycle delay,
   lockout, the sleep schedule and the addresses below), the robot bank's status and
   hardware registers, and a few in banks 04 and 05.
4. Sends `pet_profile`, then `wplus_subscription`.

Besides the registers this document names, the cloud reads these, whose meanings are
**OPEN**: bank 01 `0E`, `15`, `16`, `19`, `1C`, `26`; bank 02 `0B`, `0C`, `0E`, `0F`,
`20`, `24`, `2A`; bank 04 `01`–`03`, `06`, `07`, `0C`, `0D`; bank 05 `0E`, `18`;
bank 06 `0A`; bank 09 `0A`. All of them answer `0000` except bank 01 `16`, bank 02
`0F` and bank 06 `0A` (see [Reading state](#reading-state)); a `0000` here may be
the register's real value. Bank 02 `20` answers with a 24-bit value
(`0x0220000000`), the only reply element wider than 16 bits.

A cloud-free driver can take the same steps itself: set the clock, read the state,
and answer `pet_profile_request` if the robot is to identify pets.

## Differences from the LR4 driver

| LR4 | EVO |
|---|---|
| `0xTRRVVVV` elements, one flat register map | `0xTTBBRRVVVV`, banked |
| `requestState` returns a named state document | no state document; most registers can be read, many in one message |
| reports via `0xA0`–`0xAE` macros | macros are only acknowledged |
| panel brightness `0x0E`, packed High/Low pair switched by ambient light | bank 02 `01`, packed screen/LED pair, no ambient switching |
| night light registers `0x18`, `0x19` | no night light |
| button presses on register `0x01` | button presses on bank 01 register `01`, with the same codes (`0201` Cycle, low byte `02` for a hold) |
| empty cycle as a synthesized panel press (`0x02010801`) | empty cycle as a robot-status write (`0x020103000B`) |
| topics `prod/LR4/<serial>/…` | the app provisions `prod/robots/<serial>/…`; the robot uses whatever it is given |

## Open items

1. The remote reset command.
2. The scale of the live weight sensor (`051B`); the `usage` event's weight (`0306`) is already in hundredths of a pound.
3. Drawer-level scale (`050A`) against the cloud's `dfiLevelPercent`.
4. Bank 01 registers `04`, `06`, `08`, `09` and status values `06`, `07`; bank 03 element `05`; bank 05 registers `0B`, `0C`, `14`, `22`–`26`; the values bank 09 register `08` emits during an empty cycle.
5. Whether the status LED can be switched off outright: a level of 0 is replaced with 50.
6. Whether smart weight, dynamic cycle delay, privacy mode and sound exist on this model. The cloud defines them for the LR5 family; whether the EVO implements them is not known.
8. A command that sends a paused empty cycle home without a panel press.
9. The meanings of the registers the cloud reads at reconnect (see [Reconnect resync](#reconnect-resync)), especially bank 01 `16`, bank 02 `0F` and bank 06 `0A`, which hold non-zero values.
