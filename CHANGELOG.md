# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Thanks to [@CryingPecan](https://github.com/CryingPecan), whose LitterHopper robot
on ESP 1.4.4 is behind much of what's below. Protocol detail lives in
`docs/devices/litter-robot-4/`.

### Added

- **The clean cycle and reset buttons are back**, and this time they work: they
  synthesise the same button press the panel sends. Proven on ESP 1.1.75 and 1.4.4.
- **Empty cycle and Power buttons**, disabled by default and named `(danger)` — an
  empty cycle dumps the globe into the drawer, and Power takes the robot off the
  network. The CLI gains `empty-cycle` and `power`, which prompt first.
- **Pet weight actually works**, and reports the whole cat rather than half of it.
- **LitterHopper support**: connected, fill gauge, and an out-of-litter alert the
  firmware itself never raises. The hopper entities switch themselves on the first
  time a hopper reports.
- **Litter level as a percentage.** It calibrates itself over time; one button press
  with the globe filled to the line pins it immediately.
- **New entities**: last cat visit, last visit duration, waste drawer last moved,
  and panel brightness for bright and dark rooms.
- **Activity-derived entities survive a restart** instead of reading unknown until
  the next cat visit.
- **New install channels**: `brew install sisyphusmd/tap/whiskerless`, `.deb` and
  `.rpm` for amd64 and arm64, and standalone Linux binaries for both. None of them
  need a system Python — the audience is someone provisioning a robot from a laptop
  that has none.

### Fixed

- **The weekday sleep schedule now arms every day.** It is a per-day bitmask, not a
  switch, and turning it on armed Sunday alone — so it looked fine if you tested on
  a Sunday and did nothing all week.
- **The panel sleep schedule can actually be set.** The sleep and wake time entities
  wrote a register the firmware only computes, so they never did anything.
- **Litter readings are suppressed while the globe is not level.** Mid-cycle the
  sensors read the globe rather than the litter, and that was published as a level.
- **`robotStatus` 10 is the clean cycle** on every firmware; the old map called it a
  cat pause. The boot cycle and the filter-change wizard are mapped too — both move
  the globe, and while unmapped their readings published as real litter levels.
- **`whiskerless set night-light-mode auto` works.** Every spelling the command
  accepts used to crash — and it is the command in the README quickstart.
- **The declared Home Assistant minimum was wrong** (2025.2.0), so a user on 2025.2
  could install this and watch it fail. It is 2025.3.0.
- **Every settings write is verified** by reading it back, a multi-register write no
  longer loses one of its parts, and broker failures are reported rather than raised
  as a traceback.
- The hopper no longer drops to unknown on a link code that is not a disconnect, and
  one dispense can no longer prove an empty hopper on its own.

### Changed

- **Breaking:** `binary_sensor.<robot>_waste_drawer_removed` is replaced by
  `sensor.<robot>_waste_drawer_last_moved`. The robot reports that the drawer moved
  and never which way — nine codes turned up across removals and insertions alike.
- **Breaking:** clean cycle wait time is a number (3–30 minutes), not a select. Move
  automations from `select.<robot>_clean_cycle_wait_time` to
  `number.<robot>_clean_cycle_wait_time`.
- **Breaking (library):** `Hazard.MOTOR`, `MotorCommandError` and `allow_motor` are
  gone. A written press is the same event as a physical one, so the robot's own
  interlocks apply either way. Power still requires `allow_dangerous`.
- **Last visit duration needs ESP 1.4.4**, so it ships disabled and switches on the
  first time a robot reports one. On 1.1.75 that register has never appeared, and the
  sensor would otherwise read unknown for the life of the robot.
- **Cat detected follows the scale**, not the sensors looking into the globe, so it
  can stay on for hours after a cat leaves. Automate on it as "the robot is busy
  with a cat" rather than "there is a cat in the box right now".

## [0.1.3] - 2026-07-02

### Added

- **BLE provisioning now fails on non-LR4 devices.** The serial is validated up
  front (must be the `LR4…` form; normalized to the label's uppercase), and after
  connecting the provisioner verifies the device exposes the LR4 provisioning
  GATT service before writing anything — closing the `--address` path that
  previously accepted an arbitrary BLE address.

## [0.1.2] - 2026-06-29

### Removed

- **The clean-cycle command** — the Home Assistant button, the CLI `clean-cycle`
  subcommand, and `commands.clean_cycle()`. A live capture proved the inherited
  `0x02A30000` ("cleanCycle") opcode **resets** the robot (`odometerPowerCycles`
  increments, no cycle runs) — it was a reset disguised as a cycle, so it's gone
  rather than left shipping a surprise reboot.

### Changed

- **`0xA3` reclassified to never-send.** It's the reset / main-board-OTA
  orchestrator, not a motor command; the safety guard now refuses it unconditionally
  alongside `0xA4` / `0xAC` / `0xAD`. No motor command is exposed until a real
  cleanCycle trigger is recovered — the `MOTOR` / `allow_motor` gate stays wired but
  empty.
- **Documented the action-command hunt** in `docs/reverse-engineering.md`: the
  `0xA3` correction, why the cleanCycle / power / empty / reset dispatch lives in a
  bootloader region absent from every public OTA image, the exhaustive (and empty)
  search for a complete firmware dump, and the recovery paths (cloud-byte capture,
  app decompile, ESP-flash / PIC-ICSP dump).

## [0.1.1] - 2026-06-29

### Fixed

- The signed macOS installer (Apple Silicon + Intel) now builds and ships;
  `0.1.0` targeted the since-retired `macos-13` runner image, so that release
  shipped without the macOS `.pkg`.

## [0.1.0] - 2026-06-29

### Added

- **`whiskerless` Python library** — fully-local MQTT control + telemetry for the
  Whisker Litter-Robot 4:
  - LR4 wire codec, command catalog, and a typed state model that decodes both raw
    firmware integers and cloud-style strings defensively.
  - A push-first `LitterRobot4Client` with a self-healing MQTT connection and
    write → read-back → retry for the firmware's commit-latency registers.
  - Device-agnostic BLE (esp-idf protocomm) re-provisioning with a self-contained
    pure-Python protobuf codec (no `protoc` build step).
  - A `safety` guard that refuses brick/reset-class commands (`0xAC`/`0xA4`/`0xAD`)
    unconditionally and gates motor / untraced commands.
- **`whiskerless` CLI** — `provision`, `monitor`, `state`, `read`, `set`,
  `clean-cycle`, and a guarded raw `send`.
- **Home Assistant integration** (HACS) built to Platinum standards: fully async,
  fully typed, `local_push`, with **MQTT discovery** (robots appear as Add/Ignore
  cards), diagnostics, translations, and per-robot config entries (any number of
  robots).
- **Documentation** — protocol reference, register map, command catalog,
  compatibility matrix, setup guides, recovery guide, and the reverse-engineering
  writeup.
- **Standalone CLI binaries** built on release for users who want the BLE
  re-provisioner without installing Python.

[Unreleased]: https://github.com/SisyphusMD/whiskerless/commits/main
