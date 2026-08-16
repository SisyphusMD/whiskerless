# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

**The release where the robot stopped being read-only.** Whiskerless could always
watch a Litter-Robot 4 and change its settings; it could not press anything. The
panel button register turned out to be writable, so *Clean cycle* and *Reset* are
real buttons now — they emit the exact code the panel does, which means the
firmware's pinch, cat-detect and bonnet interlocks apply to them just as they do
to a finger. Two other things changed the day-to-day: provisioning no longer
fails silently when you mistype the WiFi password, and the CLI remembers your
robots instead of wanting a wall of flags on every command.

Thanks to [@CryingPecan](https://github.com/CryingPecan), whose LitterHopper robot
on ESP 1.4.4 is behind much of what's below. Protocol detail lives in
`docs/devices/litter-robot-4/`.

### Breaking changes

Worth reading before you upgrade; the rest of the list is safe to skim.

- **`binary_sensor.<robot>_waste_drawer_removed` → `sensor.<robot>_waste_drawer_last_moved`.**
  The robot reports *that* the drawer moved and never which way, so a binary
  sensor was claiming more than the hardware says.
- **`switch.<robot>_panel_sleep_mode` → a binary sensor.** The firmware refuses
  direct writes to it, so the switch could only ever fail. The weekday schedule
  entities are the control.
- **Clean cycle wait time is a number (3–30 minutes), not a select.**
- **Library: `Hazard.MOTOR`, `MotorCommandError` and `allow_motor` are gone.** A
  written press is the same event as a physical one, so that gate gated a hazard
  that does not exist — and every caller passed the flag unconditionally, which
  made the real gates look like the same formality. Power still requires
  `allow_dangerous`.
- **Library: `LitterRobot4Client` and `WhiskerlessAuthError` are removed.** Nothing
  used them, and the client had become a third, already-drifting copy of the
  write-verify loop.

### Added

- **Clean cycle and Reset buttons, and they actually work.** Proven on ESP 1.1.75
  and 1.4.4. This is the project's first recovered action command; the old "no
  action commands exist" framing is dead.
- **Empty cycle and Power**, shipped disabled and named `(danger)` — an empty
  cycle costs a litter refill, and a robot switched off has left the network, so
  nothing over MQTT can switch it back on. The CLI gains `empty-cycle` and
  `power`, which prompt first.
- **Provisioning verifies the WiFi join.** A mistyped passphrase used to sail
  through silently — the robot accepted everything, rebooted, and simply never
  appeared on any network, which is indistinguishable from a dead unit. The robot
  names that failure if asked, so provisioning now polls the join status and stops
  with "mistyped WiFi password" *before* touching the broker config; a confirmed
  join prints the robot's IP and moves on early. Firmware that stays silent gets
  the old wait.
- **The CLI remembers your robots.** `provision` saves the serial, broker and CA
  under `~/.whiskerless`; later commands run bare, and every flag still overrides.
  **`robots`, `use` and `forget`** list, pick and drop them — damaged profiles are
  shown as such and can still be removed.
- **`whiskerless adopt`** tells the CLI about a robot you provisioned before the
  profile store existed, so it stops needing `--serial/--host/--ca` on every
  command. It writes the same profile `provision` would and contacts nothing —
  which also means it cannot check the serial, so confirm with `whiskerless state`.
- **A second robot inherits the saved setup** — each prompt offers what your
  robots already share, so you type only the serial and the WiFi password.
- **No secret is ever saved.** The broker password is per-run
  (`WHISKERLESS_PASSWORD`), the WiFi passphrase is never kept, and the robot's
  factory certificate is never touched. `provision` does now ask for the broker
  *username* (optional, offered from what your other robots use), so an
  authenticated broker no longer needs `--username` on every later command.
- **Litter level as a percentage** — self-calibrating over time, or pinned
  instantly by one button press with the globe filled the way you consider full.
- **LitterHopper support**: connected, fill gauge, and an out-of-litter alert the
  firmware never raises. The entities enable themselves at the first dispense.
- **New entities**: last cat visit, last visit duration, waste drawer last moved,
  panel brightness for bright and dark rooms, and excess-weight detection — the
  stuck-scale condition the robot otherwise only shows on its own panel.
- **`whiskerless status`** — the robot in plain terms from a single fresh reading:
  level, drawer, faults, calibration. It names what needs a listener rather than
  printing zeros. **`whiskerless calibrate full|empty`** stores your own litter
  reference per robot and refuses a reading that cannot be one, and
  **`whiskerless panel-reset`** presses Reset.
- **Activity-derived entities survive a restart** instead of reading unknown until
  the next cat visit.
- **New install channels**: Homebrew, `.deb`/`.rpm`, and standalone Linux binaries
  for amd64 and arm64 — none of which need a system Python.
- **The CLI shows liveness and colour**: a spinner on the BLE scan (heartbeat lines
  when piped), banners on the dangerous prompts, `NO_COLOR` honoured.
  **`whiskerless --version`** works, and a bare `whiskerless` prints an
  orientation instead of a usage error.
- **The README covers the whole journey**: prerequisites, per-platform installs
  including Homebrew, everyday use, upgrading, the rc channel, uninstalling.
- **The integration has an icon and a logo**, shipped inside it and served by Home
  Assistant 2026.3+; older versions simply show what they show today.

### Fixed

- **Provisioning stops scanning the moment it finds your robot.** It used to run
  the whole `--scan-timeout` even after the robot answered — and since a robot
  only advertises while you hold Connect, that *spent* the pairing window instead
  of using it. One bench attempt found the robot and then failed to connect,
  because it had gone quiet by the time the scan ended.
- **The WiFi check no longer reports `0.0.0.0` as your robot's address.** The
  robot says "connected" the instant it associates, before DHCP hands out a
  lease, so the join is confirmed but the address is not yet known — and printing
  the unset one claimed a fact it did not have.
- **Pet weight is right again** (raw ÷ 100, the cloud's own units) — recent rc
  builds doubled the reading.
- **The weekday sleep schedule arms every day**, not just Sunday, and **the panel
  sleep and wake times can actually be set** — they now write the per-day
  registers instead of one the firmware only computes.
- **`robotStatus` 10 is the clean cycle**, with the boot cycle and filter wizard
  mapped too. Left unmapped, their readings were published as real litter levels.
- **Litter readings are suppressed while the globe is not level** — mid-cycle the
  sensors are looking at the globe, not the litter. The first reading after a
  restart is no longer discarded either.
- **The globe motor fault sensor watches the activity stream**, where the fault
  actually appears — the state document sat at 0 through a real fifty-minute
  fault. A restored fault can also clear after a missed clear event, on the proof
  of a clean cycle completing.
- **Cat detection no longer mistakes weight on the scale for a cat** — occupancy
  uses the bit that tracks the animal, not the one a misseated bonnet holds — and
  **handling the robot no longer counts as a visit**.
- **A long cat visit is no longer dropped.** The close was matched against a
  90-second window, and the cats that sit longest fell outside it. **Last cat
  visit now updates on every robot**, stamping from occupancy rather than only
  from weight events, which one robot never sends.
- **Hopper telemetry stopped lying about itself.** Detection now means litter was
  actually delivered, because the link register reports healthy on a bench and
  "disconnected" during a refill — so nothing reads it for connectivity any more.
  The level survives a restart instead of reading unknown for days, a robot that
  dispenses but rarely reports its link keeps its telemetry, one dispense cannot
  prove an empty hopper, and the upgrade sweep no longer removes hopper entities
  from a robot that has one.
- **The out-of-litter alert judges against your robot's own learned floor** —
  floors differ per unit, and a fixed cutoff could cry empty while litter was
  still flowing.
- **A restored excess-weight alarm clears once the robot reports the pan clear**,
  instead of re-firing on every later visit.
- **Event sensors appear only once their fact has been reported.** Some firmware
  never emits a drawer event or a weight, and those sensors sat unknown forever; a
  one-time sweep applies the same standard to existing installs — and a detection
  re-sweep no longer disables entities you enabled yourself.
- **`brew install sisyphusmd/tap/whiskerless` works again** (the formula pinned a
  bleak whose build backend Homebrew cannot build), and every release now
  install-tests the formula before the tap publishes.
- **Errors are sentences, not stack traces.** A Bluetooth failure reads "BLE scan
  failed: Bluetooth device is turned off"; `~` expands everywhere; every provision
  answer is checked at its prompt, including that the CA really is a PEM; file and
  broker errors print one line. `--debug` still gives you the traceback.
- **The serial validator rejects the model number** (`LR4-0301-00-US`) printed
  beside the real serial on the label.
- **`--dry-run` marks everything it prints**, so a simulation no longer describes
  writes that never happened.
- **`whiskerless set night-light-mode auto` works** — every accepted spelling used
  to crash.
- **Every settings write is verified by read-back**, multi-register writes no
  longer lose parts, and broker failures print instead of raising.
- **Fewer unknowns while calibration settles**: the calibration reference shows the
  built-in default (marked as such) and the hopper level a labelled estimate.
- **"A short press does nothing" was wrong, and dangerous.** A short press of the
  robot's **Connect** button toggles its WiFi *off* — the light bar turns white
  and the robot vanishes from your broker, looking for all the world like a dead
  unit. The README and the recovery guide both told you it was harmless. Hold
  Connect for pairing mode; tap it only to put the radio back.
- **The status a robot reports while powering down is no longer labelled
  "powering up"**, now that each half of a power cycle has been captured on its
  own rather than together.
- **The waste-drawer register no longer claims to know direction.** A brief rule
  ("it speaks on a seat and stays silent on a removal") held on one robot and
  failed on the other; whiskerless still reports only *when* the drawer last
  moved, which is all the hardware supports.
- **The declared Home Assistant minimum is correct** (2025.3.0, not 2025.2.0).

### Changed

- **Some entities were renamed, and existing installs are moved with them**:
  *Start clean cycle* → **Clean cycle**, the two calibration buttons →
  **Calibrate full** / **Calibrate empty**, *Hopper fill (raw)* → **Hopper
  reading**, *Litter calibration reference* → **Litter reference**. Entity IDs you
  chose yourself are left alone, and every rename is logged — check automations
  that referenced the old IDs.
- **The manual calibration buttons now ship disabled.** The robot calibrates
  itself; enable them if you want to pin the scale to a measurement of your own.
- **Last visit duration ships disabled and enables itself at your robot's first
  report** — not every robot emits it, and that is not a firmware split.
- **Litter distances read in millimetres**, not inches converted to thirteen
  decimal places — the unit the protocol and the docs use. Per-entity overrides
  still win.
- **The raw hopper reading, last dispense and clean-cycle count moved to
  Diagnostics**, leaving the sensor list to the things worth a glance.
- **Auto-calibration got a statistics upgrade**: a median-based outlier gate keeps
  in-band anomalies (a paw reads like an overfull globe) away from the litter
  anchors, and the hopper floor is learned from declined-into flatline runs — in
  both directions, so a floor that moved up is found as readily as one below.
- **Detections remember what proved them**, so tightening one rule can no longer
  cost you entities another rule had already earned.
- **All the derived telemetry moved into the library**, which is what will let the
  CLI show everything Home Assistant shows without a second implementation.
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
