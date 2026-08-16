<img src="https://raw.githubusercontent.com/SisyphusMD/whiskerless/main/brand/banner.png" alt="whiskerless" width="470">

<br>

**Un-cloud your Whisker devices.** Fully-local MQTT control and telemetry for the
Whisker **Litter-Robot 4** — no cloud account, no internet round-trip, no
third-party servers. Your robot talks to *your* broker, and that's it.

> **Primary repository**: developed at [forgejo.bryantserver.com/SisyphusMD/whiskerless](https://forgejo.bryantserver.com/SisyphusMD/whiskerless). The [GitHub copy](https://github.com/SisyphusMD/whiskerless) is a read-only mirror (HACS installs from it). **Please file issues and pull requests on [GitHub](https://github.com/SisyphusMD/whiskerless/issues)** — the Forgejo repository does not take external issues.

> **Status: beta.** The local protocol was recovered by reverse-engineering and
> validated against a real robot. Re-provisioning, telemetry, and settings are
> proven on hardware, and the panel actions (clean cycle, reset, empty, power) were
> recovered in August 2026 — see [What's *not* here](#whats-not-here) for what is
> still open.

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

- a **Home Assistant integration** (HACS) built against the platinum checklist —
  fully local, push-first, fully typed. (The quality scale is only awarded to
  core integrations, so that is the bar it was written to, not a badge it holds.)
- a **`whiskerless` CLI + Python library** to provision, monitor, read, and
  control a robot directly;
- a **complete, public protocol reference** — the first published map of the LR4
  local MQTT protocol.

## What using it looks like

One guided session, next to the robot, and you never touch it again:

```
$ whiskerless provision
robot serial (the unhyphenated LR4C… line on the label, …): LR4C123456
broker IP (e.g. 192.168.1.10): 192.168.1.10
path to your CA PEM: ~/certs/ca.crt
broker username (enter to skip):
WiFi SSID: MyIoT
WiFi password for 'MyIoT':
⠹ scanning for robots over BLE (3s)

  RE-PROVISION — this re-points the robot away from Whisker's cloud
    robot   F8:B3:B7:xx:xx:xx (MAC f8:b3:b7:xx:xx:xx)
    serial  LR4C123456
    broker  192.168.1.10
    wifi    MyIoT
    reversible — re-onboard the robot in the Whisker app

Proceed? Type 'yes': yes
   1 ▸ connected (MTU=500, cert chunk=460)
   2 ▸ DEVICE_ID_SET LR4C123456
   3 ▸ WiFi SetConfig+Apply ssid=MyIoT; verifying join (≤20s)
   4 ▸ WiFi connected (ip=192.168.1.42)
   5 ▸ endpoints: host=192.168.1.10 sub=prod/LR4/LR4C123456/command
   6 ▸ CERT_AWS_ROOT_CERT written (1310 bytes)
   7 ▸ APPLY_CONFIG committed
   8 ▸ DEVICE_REBOOT

reprovisioned; the robot should reconnect MQTT to 192.168.1.10

  saved as LR4C123456 — later commands need no flags:
    whiskerless state
```

(Abridged; a second robot is even shorter — every prompt offers the setup the
saved robots already share, so pressing enter accepts it.)

The robot reboots, joins *your* broker, and from then on every check and every
button press is local:

```bash
whiskerless state          # full decoded status, on demand
whiskerless monitor        # live telemetry as it happens
```

— and if you run Home Assistant, the robot **appears on its own** as a
discovered device the moment it reaches the broker. Fourteen sensors, the
buttons, and every writable setting, all local.

## What you need

Physical prerequisites, gathered up front — everything else is prompted for:

- **The robot's serial**, printed on its label (also in the Whisker app under
  the robot's settings). The label carries two lines that both start with
  "LR4"; the serial is the **unhyphenated** one:

  ```
  LR4C123456      ← the serial (LR4C + six digits) — this is what you type
  LR4-0301-00-US  ← the model number — not per-unit, not accepted
  ```

  The serial becomes the robot's MQTT identity, so it must match the label
  exactly.
- **An MQTT broker on your LAN with TLS** (port 8883) that you control —
  Mosquitto in a container, the HA add-on, anything. Setup, including making
  the certificates, is walked through in
  [docs/setup/mqtt-broker.md](docs/setup/mqtt-broker.md) and
  [docs/setup/certificates.md](docs/setup/certificates.md).
- **Your CA certificate as a PEM file** — the one that signed the broker's
  certificate. You created it during broker setup; it gets written into the
  robot, which then trusts your broker and nothing else.
- **The WiFi network and password** the robot should join (2.4 GHz).
- **A computer with Bluetooth within a few meters of the robot**, for the
  one-time provisioning. macOS, Linux, or Windows — installs below.

## How it works (30 seconds)

```
  BLE (one-time)        re-point trust + broker          runtime (forever after)
  your laptop  ───►  CA + host + topics over protocomm  ───►  robot ──MQTT/TLS──► your broker ──► Home Assistant
```

The robot stores all of its cloud identity in NVS and exposes esp-idf
**protocomm** provisioning over BLE with no PIN. whiskerless writes *your* CA into
its root-CA slot, *your* broker as its host and topics, and your WiFi details,
then commits. From then on the robot connects to your broker over TLS and speaks
plain JSON — `requestState`, settings writes, and a live telemetry stream. Full
detail in [`docs/how-it-works.md`](docs/how-it-works.md).

## Install

### Home Assistant (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/SisyphusMD/whiskerless` as an **Integration**.
2. Install **Whiskerless**, restart Home Assistant.
3. Make sure Home Assistant's **MQTT integration** is connected to your broker.
4. Provision each robot onto that broker (below). It then **appears on its own**
   under Settings → Devices & Services as a **Discovered** device — click **Add**
   and give it a name. No broker details or serials to type.

See [`docs/setup/`](docs/setup/) for the broker, certificate, and discovery details.

### The provisioning CLI

Runs on the computer near the robot. Every channel ships the same tool; none of
them needs a system Python except PyPI's.

**Homebrew (macOS and Linux):**

```bash
brew install sisyphusmd/tap/whiskerless
```

**macOS signed installer** — download the `.pkg` for your chip from the
[releases](https://github.com/SisyphusMD/whiskerless/releases)
(`whiskerless-<version>-macos-arm64.pkg` for Apple Silicon, `…-x86_64.pkg` for
Intel) and double-click. It's signed and **notarized by Apple**, so there's no
"unidentified developer" warning. The first time it scans, macOS asks to let
your terminal use Bluetooth — allow it.

**Debian, Ubuntu, Raspberry Pi OS (64-bit):**

```bash
sudo apt install ./whiskerless_<version>_amd64.deb    # arm64 for a Pi
```

(No 32-bit build — a Pi on 32-bit Raspberry Pi OS should use the PyPI route below.)

**Fedora, RHEL:**

```bash
sudo dnf install ./whiskerless-<version>.x86_64.rpm   # aarch64 for ARM
```

**openSUSE:** the same `.rpm`, via `sudo zypper install ./whiskerless-<version>.x86_64.rpm`.

**Raw Linux binary** — `whiskerless-<version>-linux-x86_64` / `…-arm64` from the
same releases page:

```bash
chmod +x ./whiskerless-<version>-linux-x86_64
./whiskerless-<version>-linux-x86_64 provision
```

**Windows** — no standalone binary, but the PyPI CLI works **natively**; `bleak`
drives Windows' built-in Bluetooth:

```powershell
uvx --from 'whiskerless[ble]' whiskerless provision
```

(Don't run the Linux binary under WSL: WSL can't reach the Bluetooth adapter,
so provisioning won't work there.)

**PyPI** — one-shot with no install, or on your PATH:

```bash
uvx --from 'whiskerless[ble]' whiskerless provision   # one-shot
pipx install 'whiskerless[ble]'                       # CLI on PATH (provisioning included)
pip install 'whiskerless[ble]'                        # library + BLE provisioning
```

The releases live on [Forgejo (primary)](https://forgejo.bryantserver.com/SisyphusMD/whiskerless/releases)
and the [GitHub mirror](https://github.com/SisyphusMD/whiskerless/releases) —
same artifacts either way.

## Provision the robot

Put the robot in pairing mode — **hold** its **Connect** button for about three
seconds, until the light **blinks yellow** — then, near it:

> ⚠️ **Hold it, do not tap it.** A *short* press toggles the robot's WiFi off.
> The light turns white and the robot vanishes from your broker, which looks
> exactly like a dead unit. Press Connect once more to bring it back.

```bash
whiskerless provision
```

It prompts for everything in [What you need](#what-you-need), checks each answer
as you give it, shows exactly what it is about to write, and asks before
touching anything. When it finishes, the robot reboots onto your broker;
`whiskerless state` is the proof. Add `--dry-run` to watch the whole flow with
nothing written.

That's the only step that needs details. whiskerless remembers the robot, your
broker and your CA under `~/.whiskerless`, so everything afterwards is bare.
Provisioning a second robot? Each later `provision` offers the broker, CA and
WiFi your saved robots already share — press enter to accept each.

> **No secret is written to `~/.whiskerless`.** If your broker requires
> authentication, supply the password per run with `WHISKERLESS_PASSWORD`
> (preferred — `--password` lands in your shell history and in `ps`).
> `provision` asks for the broker username and saves it with the robot, so later
> commands need no `--username`; the flag still overrides it. The WiFi passphrase is only needed while
> provisioning and is never kept, and the robot's factory certificate and private
> key are neither read nor written. Files are still owner-only (0600), since a
> broker address and username are worth keeping to yourself.

**Already provisioned, before this version existed?** Nothing is saved for those
robots, and re-provisioning purely to write a file would touch the robot for no
reason. Tell whiskerless about one instead:

```bash
whiskerless adopt --serial LR4C123456 --host 192.168.1.10 \
  --ca ~/certs/ca.crt --name Upstairs
```

Nothing is contacted — it writes the same profile `provision` would. Confirm with
`whiskerless state`, since a mistyped serial produces a robot that never answers
and says nothing about why.

## Everyday use

Most people live in Home Assistant afterwards — see
[docs/setup/home-assistant.md](docs/setup/home-assistant.md) for the entities
and what they mean. The CLI covers the same ground from a terminal — the
everyday controls, the raw telemetry, and the derived view of what the robot is
actually doing:

> **Anything that talks to the robot needs a route to your broker.** Provisioning
> is Bluetooth, and `robots`, `use`, `forget` and `adopt` only touch files on your
> machine — but `state`, `monitor`, `set`, `status` and the buttons all open an
> MQTT connection. If your robots live on an isolated IoT VLAN, your everyday
> machine may have no way in. A `cannot reach broker at …:8883 (timed out)` is
> most often that boundary rather than a whiskerless fault — though a wrong host
> or port, a stopped broker or a firewall look identical from here, so check those
> too. Home Assistant is already on that network, which is why it stays the
> control surface for most people.

```bash
whiskerless status                       # the robot in plain terms, one reading
whiskerless state                        # full decoded status
whiskerless monitor                      # live telemetry (ctrl-c to stop)
whiskerless calibrate full               # store your own litter reference
whiskerless set night-light-mode auto    # writes, then reads back to confirm
whiskerless clean-cycle                  # start a cycle (asks first)
whiskerless robots                       # every robot saved on this machine
whiskerless use LR4Cxxxxxx               # pick the default of several
whiskerless state --serial LR4Cyyyyyy    # or name one per command
```

Every connection flag still exists as an override (`--host`, `--ca`, `--port`,
…), so a one-off connection to somebody else's broker needs no saved profile at
all. `whiskerless forget <serial>` drops the saved details; the robot keeps
running. `whiskerless --help` lists the rest — including `read` and `send` for
protocol work.

## Upgrading

- **Home Assistant**: HACS shows the update; install it and restart HA. The
  integration pins the exact library version it was released with, so the pair
  always upgrades together.
- **Homebrew**: `brew upgrade whiskerless`.
- **macOS .pkg**: download the newer `.pkg` and double-click — it installs over
  the old one in place.
- **.deb / .rpm**: install the newer package the same way as the first one.
- **PyPI**: `pipx upgrade whiskerless` / `pip install -U whiskerless`.

`whiskerless --version` says what is on your PATH.

## Release candidates (and switching back to stable)

Release candidates go out before each stable release for testing on real
hardware:

- **Homebrew**: `brew install sisyphusmd/tap/whiskerless-rc` tracks the newest
  candidate (it conflicts with the stable formula — one or the other). When the
  stable release lands, the rc formula is re-pointed at it, so staying on
  `whiskerless-rc` converges to stable by itself; to switch channels explicitly,
  `brew uninstall whiskerless-rc && brew install sisyphusmd/tap/whiskerless`.
- **HACS**: in the integration's page, ⋮ → **Redownload** and enable showing
  beta versions to pick a candidate; redownload again without it to go back to
  stable.
- **Releases page**: candidates are marked *pre-release* and never "latest".

## Uninstalling

The robot needs nothing installed anywhere to keep running — these only remove
the tools:

- **Home Assistant**: Settings → Devices & Services → Whiskerless → ⋮ →
  **Delete** (per robot), then uninstall Whiskerless in HACS and restart. The
  full walkthrough is in
  [docs/setup/home-assistant.md](docs/setup/home-assistant.md#removing-the-integration).
- **Homebrew**: `brew uninstall whiskerless` (or `whiskerless-rc`).
- **macOS .pkg**: `sudo rm /usr/local/bin/whiskerless` — the installer places
  that one file.
- **.deb / .rpm**: `sudo apt remove whiskerless` / `sudo dnf remove whiskerless`.
- **PyPI**: `pipx uninstall whiskerless` / `pip uninstall whiskerless`.

Saved robot profiles stay in `~/.whiskerless` (they hold no secrets); delete
that folder to remove them. To put a robot back on the Whisker cloud, re-onboard
it in the Whisker app — the round trip is proven and documented in
[docs/recovery.md](docs/recovery.md).

## Safety first

This library talks straight to a robot's controller, and some opcodes can reset it
or, in the worst case, brick a control board. So it guards every send:

- **Four opcodes are refused unconditionally** (`0xA3`, `0xA4`, `0xAC`, `0xAD` —
  reset / main-board-OTA orchestrator, globe-motor OTA, flash erase, hardware reset).
  No flag lets them through.
- **The destructive panel combos are refused too** — factory reset, plug pull and
  onboarding mode are all one write away from the clean cycle, so `0x01` is
  whitelisted by *value*, not opened as a register.
- **Power needs an explicit opt-in**, because a robot switched off has left the
  network and nothing over MQTT can switch it back on.
- **Untraced / control-band / calibration writes** are refused unless you
  override them on purpose.

The routine presses — clean cycle, reset, empty — are ungated. Writing the panel
button register reproduces the exact code the panel emits, so the robot cannot tell
it from a finger, and the firmware's pinch, cat-detect and bonnet interlocks apply
either way.

The guard lives in [`safety.py`](src/whiskerless/safety.py) and *both* the CLI and
the integration funnel through it — see [`docs/devices/litter-robot-4/`](docs/devices/litter-robot-4/).

## What's *not* here

**The filter-change wizard**, and it is not coming. Its panel chord is a *long*
press, and the firmware performs short presses over MQTT while silently declining
long ones — so every hold-only function is out of reach by this route. Whisker's own
cloud has no long-press command either; it reaches those settings by writing
registers, which is what whiskerless already does for panel lockout, the night light,
the cycle delay and the sleep schedule.

**Empty and Power ship disabled by default.** Power is now proven — written to a live
robot, which powered off and emitted the same code a finger does — but it still ships
disabled, because a robot switched off has left the network and only someone standing
at it can bring it back. Empty's code is captured from a physical press and has still
never been written; it costs a litter refill to try. Enable them deliberately or use the
CLI, which prompts.

See the
[reverse-engineering writeup](docs/reverse-engineering.md#the-action-commands-how-the-panel-button-register-solved-all-of-them).
Contributions welcome.

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
- LR4 protocol: [protocol](docs/devices/litter-robot-4/protocol.md) · [commands](docs/devices/litter-robot-4/commands.md) · [registers](docs/devices/litter-robot-4/registers.md) · [compatibility](docs/devices/litter-robot-4/compatibility.md) · [capture notebook](docs/devices/litter-robot-4/capture-notebook.md)

## Adding another Whisker device

The library is structured so a new robot drops in under
`src/whiskerless/devices/<x>/` (codec + commands + state model) and
`custom_components/whiskerless/devices/<x>.py`, reusing the shared MQTT transport,
BLE provisioning, and safety guard. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Not affiliated with or endorsed by Whisker. "Litter-Robot" is a
trademark of its respective owner; this project is independent and interoperates
with hardware you own.
