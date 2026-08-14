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
  under `~/.whiskerless`, so every later command runs bare: `whiskerless state`
  instead of `whiskerless state --serial LR4Cxxxxxx --host … --ca …`. `robots`
  lists what a machine knows, `use` picks the default when you own more than one,
  and `forget` drops the saved details without touching the robot. Every flag
  still works as an override, so nothing that scripts today stops working.
- **Another robot inherits the setup already in use** — broker, CA and WiFi network
  are offered at each prompt, so only the serial and the WiFi password (which is
  deliberately never stored) have to be typed. Each field is
  judged on its own — robots that share a broker but sit on different networks are
  still offered the broker — and where the saved robots disagree, the default
  robot's value is offered instead, shown at the prompt (the CA, which cannot be
  shown, is labelled with whose it is).
- **Nothing secret is saved.** The broker password is supplied per run
  (`WHISKERLESS_PASSWORD`, or `--password` if you don't mind shell history), the
  WiFi passphrase is never kept, and the robot's factory certificate and key are
  neither read nor written. Saved files are owner-only (0600) on POSIX; on
  Windows, which has no mode bits, the user profile's own ACLs are the boundary.
- **`whiskerless --version`**, and a bare `whiskerless` now says what the tool is
  and which robots are set up, instead of an argparse usage error.
- **The CLI shows signs of life.** The BLE scan — the stretch a first-time user
  stares at with nothing moving — draws a live spinner with elapsed time (a
  heartbeat line when piped, so logs show liveness too). `monitor` and `state`
  gain color in a terminal, never in a pipe, with `NO_COLOR` and `TERM=dumb`
  honored. The empty-cycle and power prompts open with a high-visibility banner,
  so the one question that cannot be un-answered is not read at scroll speed.
  Stdlib only — no styling dependency lands in any install channel.
- **The README walks the whole journey**: what using it looks like before any
  install, the physical prerequisites gathered in one place (including which
  label line is the serial), per-platform installs including Homebrew, everyday
  use, upgrading, the release-candidate channel, and uninstalling.
- **A damaged profile is visible and removable.** `robots` lists an unreadable
  profile as such instead of silently hiding it, `forget` removes one even when
  it no longer loads, and `use` refuses to make one the default — a corrupt
  entry was previously both invisible and impossible to clear from the CLI.

- **The clean cycle and reset buttons are back**, and this time they work: they
  synthesise the same button press the panel sends. Proven on ESP 1.1.75 and 1.4.4.
- **Empty cycle and Power buttons**, disabled by default and named `(danger)` — an
  empty cycle dumps the globe into the drawer, and Power takes the robot off the
  network. The CLI gains `empty-cycle` and `power`, which prompt first.
- **Pet weight actually works.** Recent rc builds doubled the reading; weights now
  match the household scale (raw ÷ 100, the cloud's own units).
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
- **Excess weight detection.** The robot refuses to cycle while it thinks something
  is sitting on the scale, raises the condition itself after 30 minutes, and shows it
  on the panel — but says nothing about it over MQTT. One robot here sat like that for
  over two hours after a bonnet was reseated slightly off, with its clean cycle stuck
  the whole time and nothing on the dashboard to explain it. Now a sensor. Pressing
  Reset zeroes the scale and clears it.

### Removed

- **`LitterRobot4Client` (and `WhiskerlessAuthError`, which only it raised).**
  It had no consumers — the CLI drives `LitterRobot4Link`, and Home Assistant
  rides HA's own MQTT — while duplicating the write-verify-retry logic a third
  time and claiming, wrongly, to be the integration's client. If a daemon ever
  needs a supervised push client, git history has it, and building it on the
  derived-state library planned in the backlog will beat resurrecting it.

### Fixed

- **The hopper level no longer reads unknown for days after a restart** on
  robots whose hopper was proven before the gauge was persisted. The reading
  lived only in the raw sensor's restore cache, and the carry that rescues it
  ran solely inside the once-per-revision upgrade sweep — so an install already
  at the current revision restarted into an unknown level beside a raw gauge
  showing a real number, until the next dispense. The carry now runs at every
  startup (and still refuses implausible cached values).
- **`brew install sisyphusmd/tap/whiskerless` works again.** The formula pinned
  bleak 3.x, whose build backend (uv_build) Homebrew cannot build from source, so
  every install failed after the tap had already published. The formula closure
  now pins bleak 2.x (the library itself is unaffected), and every release now
  installs the rendered formula from the local sdist in a linuxbrew container
  before the tap publishes — the failure that shipped (a build backend no
  platform could build) can no longer pass silently. A macOS-only resource
  breakage could still; the closure's platform split is small and the .pkg CI
  covers the macOS binary itself.
- **A mistyped path is now a sentence, not a stack trace.** `provision` answered a
  CA path of `~/.whiskerless/ca.crt` with a `FileNotFoundError` traceback and
  PyInstaller's "Failed to execute script" — and `~` was the reason: the path is
  typed at a prompt inside the program, so the shell never expands it. `~` is now
  expanded everywhere the CLI takes a path, and file and broker errors — including
  a broker that drops mid-session — print one line and exit. (BLE-stack failures
  during provisioning can still trace back; translating them at the library
  boundary is backlog #64.) `--debug` (or `WHISKERLESS_DEBUG=1`) still gives the traceback
  for a bug report.
- **`provision` checks each answer as you give it.** The CA was read after the
  serial, broker, SSID and WiFi password had all been collected, so a typo in the
  third answer threw away all five — including a password typed blind. A bad answer
  now costs one line.
- **The serial validator no longer accepts the model number** printed beside it on
  the same label. A wrong serial provisions cleanly and then never appears on the
  broker, with no error to see.
- **`--dry-run` no longer describes writes it never performed.** It printed
  "CERT_AWS_ROOT_CERT written" and "APPLY_CONFIG committed" in the past tense, so the
  only thing distinguishing a simulation from a real run was the final line. It now
  says up front what is real (the connect, discovery and reads) and what is not.
- **The hopper entities no longer disappear from a robot that has one.** An upgrade
  sweep retired hopper detections recorded from the link register, which is right —
  that register proves nothing. But it also cleared them on robots whose hopper was
  genuinely proven, and the replacement evidence is a dispense, which only happens
  when the litter is actually low. A well-fed robot could go weeks without one. The
  sweep now recognises a previously recorded fill gauge as the proof it is, since
  only a dispense can produce that number.
- **Handling the robot no longer shows up as a cat visit.** A Reset press closes a
  visit on the same register a cat does; two of them were published as genuine
  four-minute and three-minute visits. A visit now needs something to have actually
  broken the beam, which a hand on the bonnet does not.
- **The globe motor fault sensor could sit at `off` through a real fault.** It read
  the state document, and the state document does not carry the fault: a robot raised
  one on its activity stream, held it for fifty minutes and cleared it, while
  `globeMotorFaultStatus` reported no fault in every single state document it published
  in that window. The sensor now watches both channels, and either one raising a fault
  is a fault.
- **The LitterHopper is now detected by watching it deliver litter.** The link
  register `0x57` looked like the answer, but a narrated session produced healthy
  readings from it with the hopper sitting on a bench, and its "disconnected" code
  from merely opening the hopper's drawer to refill it — so a refill could park the
  hopper sensor on *disconnected* with nothing on the wire to ever clear it. Nothing
  is derived from that register any more. **Hopper** reports connected once litter
  has actually been dispensed and never reports disconnected, because no signal for
  that exists.
- **A robot that dispenses but rarely reports its link no longer loses its hopper
  telemetry.** Requiring `0x57` to corroborate a dispense discarded every fill
  reading on such a robot and left its four hopper entities disabled indefinitely.
- **The hopper level survives a restart.** Dispensing only happens when the litter
  bed is actually low, so a well-fed robot can go days without one; the last gauge
  is now remembered instead of the level reading unknown until it next runs low.
- **Event sensors now appear only once their fact has actually been reported.** Pet
  weight, last cat visit, and waste drawer last moved start hidden and switch on at
  their first real report — some firmware never emits the drawer event or a weight,
  and those sensors read unknown forever there. A one-time sweep on upgrade applies
  the same standard to existing installs: sensors whose values were real stay, hopper
  and visit-duration detections re-prove themselves at the next report (a robot with
  a real hopper re-enables within one visit), and phantom entities disappear.
- **Last cat visit now updates on every robot.** It stamps from the occupancy signal
  itself, not only from weight events — one robot has visits but has never weighed
  anything, and its visit sensor stayed empty.
- **Cat detection no longer mistakes weight on the scale for a cat.** The occupancy
  field is two bits — one for what the robot can see, one for what it can feel — and
  a bonnet reseated slightly off held the second bit for over two hours, which the
  robot itself reports as an "excess weight" fault. Occupancy and litter calibration
  now use the bit that tracks the animal.
- **Fewer unknowns while calibration settles.** The litter calibration reference
  shows the built-in default (marked `source: default`) instead of unknown, and the
  hopper level shows a labelled estimate until the empty floor has actually been
  learned.
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
- **The out-of-litter alert judges against your robot's own learned floor**, not a
  fixed gauge threshold taken from one unit. Floors differ per robot — one unit's
  stocked readings sit below another's empty flatline — so the fixed cutoff could
  cry empty while litter still flowed. Until the floor is confirmed (which the
  first genuine empty itself teaches), the alert stays quietly off.
- **A restored "excess weight" alarm clears when the robot says the pan is clear.**
  It used to survive the clear and re-fire at second zero of every later cat visit
  for the rest of the session.
- **A restored globe-motor fault can finally turn off after a missed clear.** If
  Home Assistant was down when the fault cleared, the alarm re-restored itself on
  every restart forever; a clean cycle completing without a fault event now clears
  it, since a faulting cycle would have raised one.
- **A detection re-sweep no longer disables entities you enabled yourself.**
  Retiring old detection evidence used to revert a deliberately enabled pet-weight
  or hopper entity on every evidence-standard revision.

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
- **Last visit duration is not reported by every robot**, so it ships disabled and
  switches on the first time yours reports one, rather than reading unknown for the
  life of a robot that never will. This was thought to be a firmware split; it is not.
  Two robots on the same ESP build sit either side of it.
- **The raw binaries and the macOS installer now carry the version in their
  filename** (`whiskerless-<version>-linux-x86_64`,
  `whiskerless-<version>-macos-arm64.pkg`) — a file sitting in Downloads now
  says which release it came from, pairing with `--version` for the running one.
  The naming scheme is documented in `packaging/README.md`.
- **Breaking:** `switch.<robot>_panel_sleep_mode` is now
  `binary_sensor.<robot>_panel_sleep_mode`. The firmware computes that register
  from the weekday schedule and refuses direct writes, so the switch was a control
  that could only time out and error. The weekday sleep schedule switch and the
  sleep/wake time entities are the writable path.

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
