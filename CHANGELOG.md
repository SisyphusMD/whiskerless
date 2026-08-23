# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

**The release where the robot stopped being read-only.** Clean cycle and Reset are real
buttons now, and whiskerless issues the certificates your broker needs.

Thanks to [@CryingPecan](https://github.com/CryingPecan), whose LitterHopper robot is behind
much of the hopper work.

### Breaking changes

- Broker usernames and passwords are gone. Authentication is by certificate, or anonymous if you pick it.
- Every robot gets its own certificate, with no way to opt out.
- whiskerless must be able to sign unless you use `setup --auth supplied` or `--auth anonymous`. See **Upgrading from 0.1.3**.
- One broker per store. `--host` and `--ca` moved onto `setup`; point `WHISKERLESS_HOME` at a second store.
- `--port` and `--insecure` are gone. The robot's firmware fixes both.
- `whiskerless adopt` is removed. Re-provision instead.
- The store moved to `~/whiskerless`, migrated from `~/.whiskerless` on first run.
- `binary_sensor.…_waste_drawer_removed` is now `sensor.…_waste_drawer_last_moved`.
- `switch.…_panel_sleep_mode` is now a binary sensor. Use the weekday schedule entities.
- Clean cycle wait time is a number (3 to 30 minutes), not a select.
- Library: `Hazard.MOTOR`, `MotorCommandError`, `allow_motor`, `LitterRobot4Client` and `WhiskerlessAuthError` are removed.

### Added

- Clean cycle and Reset buttons. Empty cycle, Power and WiFi ship disabled and marked `(danger)`.
- whiskerless runs a certificate authority for you and prints the files your broker needs.
- Litter level as a percentage, self-calibrating or pinned with one press.
- LitterHopper support, including an out-of-litter alert the firmware never raises.
- New install channels: apt, dnf, Homebrew, `.deb`/`.rpm`, a notarized macOS `.pkg`, and Linux binaries.
- `whiskerless backup` and `restore` put the whole store in one optionally-encrypted file.
- The CLI remembers your robots, with `robots`, `use`, `forget` and `rename`.
- `whiskerless diagnose` asks the robot over Bluetooth when the panel only says "blinking blue".
- `whiskerless uninstall` finds every copy on the machine and asks before removing any.
- New entities: last cat visit, visit duration, panel brightness, and excess-weight detection.
- Provisioning verifies the WiFi join, so a mistyped password fails loudly.
- A once-a-day update check that names the right upgrade command for how you installed.

### Fixed

- Cat detection no longer counts handling the robot as a visit, and long visits are not dropped.
- Litter readings taken during a clean cycle are no longer published as real levels.
- The globe motor fault sensor now catches faults it used to sleep through.
- Provisioning survives a network list that is not a multiple of four.
- Provisioning warns that holding Connect wipes the robot's saved WiFi.
- The robot's IP address is reported when the firmware gives a usable one, instead of a moment too early.
- The waste drawer says when its number has not been measured yet.
- Panel sleep and wake times can be set, and the schedule arms every day rather than only Sunday.
- `whiskerless setup` survives a long hostname and reports a broker certificate it did not issue.
- Errors are sentences, not stack traces. `--debug` adds a request log with secrets left out.
- The declared Home Assistant minimum is correct (2025.3.0).

### Changed

- The Refresh button is on by default, on existing installs too.
- Manual calibration buttons ship disabled, because the robot calibrates itself.

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
