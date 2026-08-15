# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Thanks to [@CryingPecan](https://github.com/CryingPecan), whose LitterHopper robot
on ESP 1.4.4 is behind much of what's below. Protocol detail lives in
`docs/devices/litter-robot-4/`.

### Added

- **The CLI remembers your robots.** `provision` saves the serial, broker and CA
  under `~/.whiskerless`; later commands run bare, and every flag still overrides.
- **`robots`, `use` and `forget`** list, pick and drop saved robots — damaged
  profiles are shown as such and can still be removed.
- **A second robot inherits the saved setup** — each prompt offers what your robots
  already share, so you type only the serial and the WiFi password.
- **No secret is ever saved**: the broker password is per-run (`WHISKERLESS_PASSWORD`),
  the WiFi passphrase is never kept, the factory certificate is never touched.
- **Provisioning asks for a broker username** (optional, and offered from what your
  other robots use) — an authenticated broker used to need `--username` on every
  later command. The password is still per-run and never written down.
- **`whiskerless status`** — the robot in plain terms from a single fresh reading:
  level, drawer, faults, calibration. It names what needs a listener rather than printing zeros.
- **`whiskerless calibrate full|empty`** stores your own litter reference per robot,
  and refuses a reading that cannot be one. **`whiskerless panel-reset`** presses Reset.
- **`whiskerless --version`**, and a bare `whiskerless` prints an orientation
  instead of a usage error.
- **The CLI shows liveness and color**: a spinner on the BLE scan (heartbeat lines
  when piped), banners on the dangerous prompts, `NO_COLOR` honored.
- **The README covers the whole journey**: prerequisites, per-platform installs
  including Homebrew, everyday use, upgrading, the rc channel, uninstalling.
- **Clean cycle and Reset buttons are back, and they work** — they synthesise the
  panel's own button press. Proven on ESP 1.1.75 and 1.4.4.
- **Empty cycle and Power buttons**, disabled by default and named `(danger)`;
  the CLI gains `empty-cycle` and `power`, which prompt first.
- **Pet weight actually works** (raw ÷ 100, the cloud's own units) — recent rc
  builds doubled the reading.
- **LitterHopper support**: connected, fill gauge, and an out-of-litter alert the
  firmware never raises; the entities enable themselves at the first dispense.
- **Litter level as a percentage** — self-calibrating over time, or pinned
  instantly by one button press with the globe filled to the line.
- **New entities**: last cat visit, last visit duration, waste drawer last moved,
  panel brightness for bright and dark rooms, and excess-weight detection (the
  stuck-scale condition the robot otherwise only shows on its panel).
- **Activity-derived entities survive a restart** instead of reading unknown
  until the next cat visit.
- **New install channels**: Homebrew, `.deb`/`.rpm` and standalone Linux binaries
  for amd64 and arm64 — none of them need a system Python.

### Removed

- **`LitterRobot4Client` and `WhiskerlessAuthError`** — nothing used them, and
  the client was a third, already-drifting copy of the write-verify loop.

### Fixed

- **The hopper level no longer reads unknown for days after a restart** — a gauge
  stranded in the restore cache is carried into the saved options at every startup.
- **`brew install sisyphusmd/tap/whiskerless` works again** (the formula pinned a
  bleak whose build backend Homebrew cannot build), and every release now
  install-tests the formula before the tap publishes.
- **A Bluetooth failure is a sentence too** — "BLE scan failed: Bluetooth device is
  turned off" instead of a bleak traceback.
- **A mistyped path is a sentence, not a stack trace**: `~` expands everywhere,
  every provision answer is checked at its prompt (including that the CA really
  is a PEM), and file or broker errors print one line — `--debug` for tracebacks.
- **The serial validator rejects the model number** (`LR4-0301-00-US`) printed
  beside the real serial on the label.
- **`--dry-run` marks everything it prints**, so a simulation no longer describes
  writes that never happened.
- **Hopper entities no longer disappear from a robot that has one** — the upgrade
  sweep accepts a recorded fill gauge as proof, since only a dispense produces one.
- **Handling the robot no longer counts as a cat visit** — a visit requires the
  beam actually broken, which a hand on the bonnet does not do.
- **The globe motor fault sensor watches the activity stream too** — the state
  document stayed at 0 through a real fifty-minute fault.
- **Hopper detection means litter actually delivered** — the link register fires
  healthy on a bench and "disconnected" on a refill, so nothing reads it anymore.
- **A robot that dispenses but rarely reports its link keeps its hopper telemetry.**
- **The hopper level survives a restart** — the last gauge is remembered instead
  of reading unknown until the next dispense.
- **Event sensors appear only once their fact has been reported** — some firmware
  never emits a drawer event or a weight, and those sensors sat unknown forever;
  a one-time sweep applies the same standard to existing installs.
- **Last cat visit updates on every robot** — it stamps from occupancy, not only
  from weight events, which one robot never sends.
- **Cat detection no longer mistakes weight on the scale for a cat** — occupancy
  uses the bit that tracks the animal, not the one a misseated bonnet holds.
- **Fewer unknowns while calibration settles**: the calibration reference shows
  the built-in default (marked so) and the hopper level a labelled estimate.
- **The weekday sleep schedule arms every day**, not just Sunday.
- **The panel sleep and wake times can actually be set** — they now write the
  per-day registers instead of one the firmware only computes.
- **Litter readings are suppressed while the globe is not level** — mid-cycle the
  sensors see the globe, not the litter.
- **`robotStatus` 10 is the clean cycle**, and the boot cycle and filter wizard
  are mapped too — unmapped, their readings published as real litter levels.
- **`whiskerless set night-light-mode auto` works** — every accepted spelling
  used to crash.
- **The declared Home Assistant minimum is correct** (2025.3.0, not 2025.2.0).
- **Every settings write is verified by read-back**, multi-register writes no
  longer lose parts, and broker failures print instead of raising.
- The hopper no longer drops to unknown on a non-disconnect link code, and one
  dispense cannot prove an empty hopper on its own.
- **The out-of-litter alert judges against your robot's own learned floor** —
  floors differ per unit, and a fixed cutoff could cry empty while litter flowed.
- **A restored excess-weight alarm clears once the robot reports the pan clear**,
  instead of re-firing on every later visit.
- **A restored globe-motor fault can clear after a missed clear event** — a clean
  cycle completing without a fault event is the proof.
- **A detection re-sweep no longer disables entities you enabled yourself.**
- **A long cat visit is no longer dropped** — the close was matched against a
  90-second window, and the cats that sit longest fell outside it.
- **The first litter reading after a restart is no longer discarded**, and a
  hopper's own readings can no longer be undone by the upgrade that enabled it.

### Changed

- **Some entities were renamed**, and existing installs are moved with them:
  *Start clean cycle* → **Clean cycle**, the two calibration buttons → **Calibrate
  full** / **Calibrate empty**, *Hopper fill (raw)* → **Hopper reading**, *Litter
  calibration reference* → **Litter reference**. Entity IDs you chose yourself are
  left alone; every rename is logged, so check automations that used the old IDs.
- **The raw hopper reading, last dispense and clean-cycle count moved to
  Diagnostics**, leaving the sensor list to the things worth a glance.
- **The manual calibration buttons now ship disabled.** The robot calibrates
  itself; enable them if you want to pin the scale to a measurement of your own.
- **Litter distances read in millimetres**, not inches converted to thirteen
  decimal places — the unit the protocol and the docs use. Per-entity overrides win.
- **Detections remember what proved them**, so tightening one rule can no longer
  cost you entities another rule had already earned.
- **All the derived telemetry moved into the library**, which is what will let the
  CLI show everything Home Assistant shows without a second implementation.
- **Auto-calibration got a statistics upgrade**: a median-based outlier gate keeps
  in-band anomalies (a paw reads like an overfull globe) away from the litter
  anchors, and the hopper floor is learned from declined-into flatline runs — in
  both directions, so a floor that moved up is found as readily as one below.
- **Breaking:** `binary_sensor.<robot>_waste_drawer_removed` is now
  `sensor.<robot>_waste_drawer_last_moved` — the robot never says which way it moved.
- **Breaking:** clean cycle wait time is a number (3–30 minutes), not a select.
- **Breaking (library):** `Hazard.MOTOR`, `MotorCommandError` and `allow_motor`
  are gone — a written press is the same event as a physical one. Power still
  requires `allow_dangerous`.
- **Breaking:** `switch.<robot>_panel_sleep_mode` is now a binary sensor — the
  firmware refuses direct writes, so the switch could only fail; the weekday
  schedule entities are the control.
- **Last visit duration ships disabled and enables at your robot's first report** —
  not every robot emits it, and it is not a firmware split.
- **Release binaries and the macOS installer carry the version in the filename**
  (`whiskerless-<version>-linux-x86_64`); the scheme is in `packaging/README.md`.

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
