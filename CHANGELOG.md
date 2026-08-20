# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

**The release where the robot stopped being read-only.** Clean cycle and Reset are
real buttons now, and whiskerless issues the certificates your broker needs
instead of leaving that to you.

Thanks to [@CryingPecan](https://github.com/CryingPecan), whose LitterHopper robot
is behind much of the hopper work. Protocol detail lives in
`docs/devices/litter-robot-4/`.

### Breaking changes

- **Broker usernames and passwords are gone** — `--username`, `--password` and
  `WHISKERLESS_PASSWORD`. Everything authenticates by certificate now.
- **One broker per machine.** `--host` and `--ca` moved off the everyday commands
  onto `setup`. A separate broker is a separate store: point `WHISKERLESS_HOME` at
  it.
- **`--port` and `--insecure` are gone.** The robot's port is fixed in its firmware
  and it always checks the broker's name, so both could only point the CLI somewhere
  the robot cannot follow. A saved port is ignored, not an error.
- **`whiskerless adopt` is removed.** Re-provision instead.
- **The store moved to `~/whiskerless`.** Your old `~/.whiskerless` is moved there
  on first run, and settings 0.2.0 no longer reads are dropped from your robot
  profiles at the same time. That run tells you what changed.
- **Every robot gets a certificate of its own, with no way to opt out.** A robot
  holding one still works on a broker that allows anonymous clients, so there was
  nothing to trade — and `whiskerless robots` marks any robot still presenting the
  certificate it shipped with.
- **whiskerless has to be able to sign now, unless you say otherwise.** A store
  holding a CA certificate but not its key is no longer an unstated arrangement —
  it read like a finished setup while quietly refusing to issue anything. `setup`
  asks for the key, or offers a new authority; the second answer means
  re-provisioning every robot. See **Upgrading from 0.1.3** in the README for what
  that costs at the robot and at the broker.
- **`setup --auth` records how your store authenticates**, for a signing key that
  lives somewhere else on purpose. `supplied` takes a certificate per robot from
  `provision --robot-cert/--robot-key` and never wants the CA key; `anonymous`
  leaves robots the certificate they shipped with. The mode is stored, so later
  commands behave the same way with no flags, and a mode your files can no longer
  carry out is an error naming both rather than a silent downgrade.
- **Each robot's certificate is kept** at `robots/<serial>/client/`, where this
  machine's has always been kept at `client/`. A robot re-provisioned stays the
  same client to your broker, so ACLs and log lines keyed to it still point at it;
  `provision --reissue` replaces one deliberately. `provision` now says to back up
  afterwards, because it leaves behind material an earlier backup does not have.
- **Certificates you supply are checked before anything is written**: they have to
  chain to your CA, be valid now, not be a CA themselves, and carry the robot's
  serial as their common name — which is where a broker gets the robot's username.
  Nothing is filed until it passes, and a robot's is filed only once the robot has
  accepted it, so a rejected or aborted run leaves the one you were using intact.
- **`binary_sensor.…_waste_drawer_removed` → `sensor.…_waste_drawer_last_moved`.**
  The robot never reports which way the drawer moved.
- **`switch.…_panel_sleep_mode` is now a binary sensor** — the firmware refuses
  direct writes. Use the weekday schedule entities.
- **Clean cycle wait time is a number (3–30 minutes), not a select.**
- **Library:** `Hazard.MOTOR`, `MotorCommandError`, `allow_motor`,
  `LitterRobot4Client` and `WhiskerlessAuthError` are removed. Power still needs
  `allow_dangerous`.

### Added

- **Clean cycle and Reset buttons.** Empty cycle, Power and WiFi ship disabled and
  marked `(danger)` — each costs a litter refill or takes the robot off the
  network. The CLI gains `empty-cycle`, `power` and `wifi-toggle`.
- **whiskerless runs a certificate authority for you.** `whiskerless setup` makes
  the CA, your broker's certificate and this machine's identity, then prints the
  three files your broker needs. Bring your own with `--ca` and `--ca-key`.
- **Each robot gets its own certificate**, written over BLE and named for its
  serial — so your broker can stop accepting anonymous clients.
- **`whiskerless backup` and `whiskerless restore`** — the whole store in one
  optionally-encrypted file. The CA key is the one thing you cannot regenerate.
- **The CLI remembers your robots.** `provision` saves them; `robots`, `use` and
  `forget` manage them. A second robot asks only for its serial and WiFi password.
- **Provisioning verifies the WiFi join**, so a mistyped password fails loudly
  instead of leaving you a robot that never appears.
- **Litter level as a percentage** — self-calibrating, or pinned with one press.
- **LitterHopper support**: connected, fill gauge, and an out-of-litter alert the
  firmware never raises. A dispense arrives as three messages ~20 s apart, so the
  level survives a restart and one dispense cannot prove an empty hopper.
- **New entities**: last cat visit, visit duration (disabled until your robot
  proves it reports one), waste drawer last moved, panel brightness for bright and
  dark rooms, and excess-weight detection.
- **`whiskerless status`, `calibrate` and `panel-reset`.**
- **`whiskerless diagnose`** — when the panel says "blinking blue" and nothing else,
  this asks the robot itself over Bluetooth. It reads and writes nothing. Reaching
  the robot needs pairing mode, which takes it off WiFi, so it warns, asks first, and
  costs a re-provision — and the answer is often just "the robot is trying to
  connect", which is the state the command itself caused. It says so rather than
  inventing a diagnosis. When the robot does volunteer a verdict — refused, network
  not found, or joined-without-an-address — that verdict is real and worth the trip.
- **New install channels**: apt and dnf repositories, Homebrew with prebuilt
  bottles, `.deb`/`.rpm`, a signed macOS `.pkg`, and standalone Linux binaries —
  none of which need a system Python. Packages are GPG-signed
  (`4BBACD5A6FF38564`); setup is in the README.

### Fixed

- **Cat detection no longer mistakes weight on the scale for a cat**, handling the
  robot is not a visit, and long visits are no longer dropped.
- **`robotStatus` 10 is the clean cycle.** Unmapped, its readings were published as
  real litter levels. Readings are also suppressed while the globe is not level.
- **The globe motor fault sensor watches the activity stream**, where the fault
  actually appears — the state document sat at 0 through a real fifty-minute fault.
- **Panel sleep and wake times can be set**, and the weekday schedule arms every
  day rather than only Sunday.
- **`whiskerless setup` survives a long hostname**, and reissues the broker's
  certificate when you move the broker — if it holds your CA's key. A certificate
  it did not issue is reported, never overwritten.
- **Provisioning works where the network list is not a multiple of four.** The
  robot's WiFi scan is fetched in pages, and the last page asked for more than
  remained — which this firmware answers by dropping the Bluetooth link, halfway
  through provisioning. It looked like flaky Bluetooth.
- **Provisioning tells you to hold Connect until the light blinks yellow**, and
  stops scanning the moment it finds your robot — it only advertises while you hold
  the button, and the scan was spending that window. The instruction used to say to
  hold "until it beeps"; the robot has no beep, so the one cue it offered was for
  something that never happens.
- **The waste drawer says when its number has not been measured.** A Reset zeroes
  the gauge and the robot flags the result as unconfirmed until the next cycle's
  lasers take a real reading — `whiskerless status` was printing that placeholder as
  a measurement. In Home Assistant the sensor keeps publishing the value, so
  nothing keyed on it breaks, and carries a `level_provisional` attribute instead.
- **Provisioning warns that holding Connect wipes the robot's saved WiFi.** The robot
  forgets its network the moment it enters pairing mode, does not come back on its
  own, and cannot be taken out of that mode by any button — only a completed
  provision restores it. This is the robot's behaviour, and it strands cloud users
  too; whiskerless just never said so.
- **The network list explains itself**, with a legend for the password marker, the
  signal bars and the channel, and a clearer way to enter a hidden SSID than a bare
  `-`. The confirmation screen's `identity` row no longer sits a column out.
- **The robot's IP address is reported when the firmware gives a usable one.** It
  answers "connected" before DHCP replies, so the address was read a moment too
  early; provisioning now waits for it. Some robots report an address that is not
  theirs, so only a plausible LAN lease is shown — and when none arrives the step
  simply says the WiFi is connected, which is what it verified either way.
- **Errors are sentences, not stack traces.** `--debug` gives the traceback and
  the request log — with the WiFi password and the robot's key left out of it.
- **A short press of Connect toggles WiFi off**, which the docs called harmless —
  the robot vanishes from your broker and looks dead. Hold it for pairing mode.
- **The declared Home Assistant minimum is correct** (2025.3.0).

### Changed

- **The Refresh button is on by default**, on existing installs too.
- **Manual calibration buttons ship disabled** — the robot calibrates itself.

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
