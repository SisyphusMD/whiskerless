# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
