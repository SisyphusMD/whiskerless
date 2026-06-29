# whiskerless

**Un-cloud your Whisker devices.** Fully-local MQTT control and telemetry for the
Whisker **Litter-Robot 4** — no cloud account, no internet round-trip, no
third-party servers. Your robot talks to *your* broker, and that's it.

> **Primary repository**: developed at [forgejo.bryantserver.com/SisyphusMD/whiskerless](https://forgejo.bryantserver.com/SisyphusMD/whiskerless). The [GitHub copy](https://github.com/SisyphusMD/whiskerless) is a read-only mirror (HACS installs from it). **Please file issues and pull requests on [GitHub](https://github.com/SisyphusMD/whiskerless/issues)** — the Forgejo repository does not take external issues.

> **Status: beta.** The local protocol was recovered by reverse-engineering and
> validated against a real robot. Re-provisioning, telemetry, settings, and the
> clean cycle are proven on hardware. A few discrete actions (power, empty,
> resets) are intentionally left out — see [What's *not* here](#whats-not-here).

<!-- A screenshot/GIF of the Home Assistant device page goes here once captured. -->

---

## Why

Out of the box, a Litter-Robot 4 only works through Whisker's AWS cloud: every
status update and every button press makes a round-trip to the internet, and
Whisker actively blocks third-party clients. whiskerless cuts the cloud out
entirely. The robot keeps its firmware; you just re-point its MQTT trust + broker
at your own, over its own BLE provisioning channel — **no teardown, no UART, no
reflash, and fully reversible**.

You get:

- a **Home Assistant integration** (HACS) built to the **Platinum** quality bar —
  fully local, push-first, fully typed;
- a **`whiskerless` CLI + Python library** to provision, monitor, read, and
  control a robot directly;
- a **complete, public protocol reference** — the first published map of the LR4
  local MQTT protocol.

## How it works (30 seconds)

```
  BLE (one-time)        re-point trust + broker          runtime (forever after)
  your laptop  ───►  CA + host + topics over protocomm  ───►  robot ──MQTT/TLS──► your broker ──► Home Assistant
```

The robot stores all of its cloud identity in NVS and exposes esp-idf
**protocomm** provisioning over BLE with no PIN. whiskerless writes *your* CA into
its root-CA slot and *your* broker IP as its host, then commits. From then on the
robot connects to your broker over TLS and speaks plain JSON — `requestState`,
settings writes, clean cycle, and a live telemetry stream. Full detail in
[`docs/how-it-works.md`](docs/how-it-works.md).

## Install

### Home Assistant (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/SisyphusMD/whiskerless` as an **Integration**.
2. Install **Whiskerless**, restart Home Assistant.
3. Make sure Home Assistant's **MQTT integration** is connected to your broker.
4. Provision each robot onto that broker (below). It then **appears on its own**
   under Settings → Devices & Services as a **Discovered** device — click **Add**
   and give it a name. No broker details or serials to type.

See [`docs/setup/`](docs/setup/) for the broker, certificate, and discovery details.

### The "app" — no Python needed (for provisioning)

Re-provisioning happens over Bluetooth from a computer near the robot. Grab the
build for your OS from the releases page —
[Forgejo (primary)](https://forgejo.bryantserver.com/SisyphusMD/whiskerless/releases)
or [GitHub (mirror)](https://github.com/SisyphusMD/whiskerless/releases):

- **macOS** — download the **signed installer** for your chip
  (`whiskerless-macos-arm64.pkg` for Apple Silicon, `whiskerless-macos-x86_64.pkg`
  for Intel), double-click to install, then run it in any terminal:

  ```bash
  whiskerless provision      # prompts for everything
  ```

  It's signed and **notarized by Apple**, so there's no "unidentified developer"
  warning. The first time it scans, macOS asks to let your terminal use
  Bluetooth — allow it. To update later, just download the newer `.pkg` and
  double-click — it installs over the old one in place.

- **Linux** — download `whiskerless-linux-x86_64` and run it:

  ```bash
  chmod +x ./whiskerless-linux-x86_64
  ./whiskerless-linux-x86_64 provision
  ```

- **Windows** — no standalone binary, but the PyPI CLI works **natively** —
  `bleak` drives Windows' built-in Bluetooth:

  ```powershell
  uvx whiskerless provision
  ```

  (Don't run the Linux binary under WSL: WSL can't reach the Bluetooth adapter,
  so provisioning won't work there.)

Prefer not to install anything? `uvx whiskerless provision` runs it one-shot.

### CLI / library (PyPI)

```bash
uvx whiskerless provision         # one-shot, no install
pipx install whiskerless          # CLI on your PATH
pip install 'whiskerless[ble]'    # library + BLE re-provisioning
```

## Quickstart (CLI)

```bash
# 1. Re-provision the robot onto your broker (one-time, over BLE).
#    Prompts for anything you omit; --host-ip is your broker's address.
whiskerless provision --serial LR4Cxxxxxx --host-ip <broker-ip> --ca ca.crt --wifi-ssid MyIoT

# 2. Watch it.
whiskerless monitor --serial LR4Cxxxxxx --host <broker-ip> --ca ca.crt

# 3. Read its decoded state.
whiskerless state --serial LR4Cxxxxxx --host <broker-ip> --ca ca.crt

# 4. Change a setting (writes, then reads back to confirm).
whiskerless set night-light-mode auto --serial LR4Cxxxxxx --host <broker-ip> --ca ca.crt

# 5. Run a clean cycle (asks for confirmation first).
whiskerless clean-cycle --serial LR4Cxxxxxx --host <broker-ip> --ca ca.crt
```

## Safety first

This library can put commands on the wire that drive a motor or, in the worst
case, brick a control board. So it guards every send:

- **Three opcodes are refused unconditionally** (`0xAC`, `0xA4`, `0xAD` — flash
  erase, globe-motor OTA, hardware reset). No flag lets them through.
- The **clean cycle** (the only motor command) requires explicit opt-in and the
  CLI/integration gate it behind a confirmation.
- **Untraced / control-band / calibration writes** are refused unless you
  override them on purpose.

The guard lives in [`safety.py`](src/whiskerless/safety.py) and *both* the CLI and
the integration funnel through it — see [`docs/devices/litter-robot-4/`](docs/devices/litter-robot-4/).

## What's *not* here

Power on/off, the empty cycle, and the panel/drawer resets are **deliberately
omitted**. Reverse-engineering could not pin their exact register+value to safe,
actionable confidence (the relevant firmware partition is physically absent from
the public image and the candidates are unproven and contradictory). Shipping
them as guesses would risk dangerous control-band writes. They're tracked as open
items with a clear path to close them — see
[`docs/devices/litter-robot-4/compatibility.md`](docs/devices/litter-robot-4/compatibility.md)
and the issue templates. Contributions welcome.

## Repository layout

```
whiskerless/
├─ src/whiskerless/            # the pip library (codec, MQTT, BLE, safety, CLI)
│  └─ devices/litter_robot_4/  # LR4 protocol: codec, commands, state model, link
├─ custom_components/whiskerless/  # the Home Assistant integration (depends on the lib)
├─ docs/                       # protocol reference + setup + recovery guides
├─ examples/                   # example automations
└─ tests/                      # codec / safety / command / integration tests
```

## Documentation

- [How it works](docs/how-it-works.md) · [Reverse-engineering writeup](docs/reverse-engineering.md) · [Recovery](docs/recovery.md)
- Setup: [MQTT broker](docs/setup/mqtt-broker.md) · [Certificates](docs/setup/certificates.md) · [Home Assistant](docs/setup/home-assistant.md)
- LR4 protocol: [protocol](docs/devices/litter-robot-4/protocol.md) · [commands](docs/devices/litter-robot-4/commands.md) · [registers](docs/devices/litter-robot-4/registers.md) · [compatibility](docs/devices/litter-robot-4/compatibility.md)

## Adding another Whisker device

The library is structured so a new robot drops in under
`src/whiskerless/devices/<x>/` (codec + commands + state model) and
`custom_components/whiskerless/devices/<x>.py`, reusing the shared MQTT transport,
BLE provisioning, and safety guard. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Not affiliated with or endorsed by Whisker. "Litter-Robot" is a
trademark of its respective owner; this project is independent and interoperates
with hardware you own.
