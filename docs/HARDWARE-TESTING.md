# Hardware bench qualification

This is the release-candidate qualification plan for real Litter-Robot 4 hardware. It complements
the off-hardware Python and integration suites; it does not replace them. The automated suites
prove the commands, safety gates and profile logic the tool *would* exercise. The bench proves that
real BLE, the robot's firmware, the broker's mutual-TLS listener, DHCP timing and the packaged
artifacts behave the same way.

There is no bench runner here. The sibling `dreame-valetudo` ships one because its campaign drives
destructive flashes that must be gated and evidenced by code; whiskerless writes configuration over
BLE and sends MQTT commands, so its qualification is an operator following this document with a
capture running. That divergence is intended and belongs in `project-standard/VARIANCE.md`.

Host qualification is separate and automatic. CI covers the Linux package matrix, the native macOS
matrix, the Homebrew bottles and the install matrix on every RC. The bench proves only what those
cannot reach: a robot.

## What a qualification run binds to

A run is evidence about one **build**, one **install channel**, one **robot**, and one **ESP
firmware**. Record all four or the report cannot be read later.

Firmware is not a footnote. The rc.34 qualification was performed on two robots **both running ESP
1.1.75**, and it says nothing about 1.4.4. A run on one firmware is not transferable to another.

**Install from the published artifact.** An editable install from `src/` passes the same commands
while proving nothing about what users receive — the rc.34 run used the Homebrew bottle and
confirmed `poured_from_bottle: True`. Qualify the channel you intend people to use.

## Safety classes

| Class | Meaning | Attendance |
|---|---|---|
| **W0** | Host-only. No robot, no broker. `robots`, `use`, `rename`, `forget`, `uninstall`, `setup`, `backup`, `restore` | unattended |
| **W1** | Read-only against a live robot. `state`, `status`, `monitor`, `read` | unattended |
| **W2** | Writes that leave the robot reachable. `clean-cycle`, `empty-cycle`, `panel-reset`, `calibrate`, `set`, `send` within `PANEL_BUTTON_SAFE` | attended |
| **W3** | Takes the robot off the air. `power`, `wifi-toggle` | attended, physical access required |
| **W4** | Rewrites the robot's stored configuration. `provision` | attended, physical access required |

Two buttons remove the robot from the network, not one. `power` can leave it off and unreachable;
`wifi-toggle` (Connect) silences it within 0.8s. **Silence is indistinguishable from "did
nothing"**, so neither can be scored from telemetry alone.

`NEVER_SEND_OPCODES` — `0xA3`, `0xA4`, `0xAC`, `0xAD` — are refused unconditionally and are not a
bench subject. Nothing in a campaign may be designed to reach them.

**Pairing mode is destructive to connectivity.** Entering it wipes the robot's saved WiFi, and only
a **completed** provision restores it; nothing about it expires when the button is released. Every
W4 scenario therefore starts by taking the robot off the network, and an abandoned provision leaves
it there.

## Bench inventory

Record before starting: robot serial slot (anonymous key, not the serial), ESP firmware, main-board
build/revision, broker host and listener mode, install channel, RC tag, and the package SHA-256.

**Never record** the serial itself, the CA signing key, robot certificates or private keys, the
WiFi password, or raw `--debug` output that has not been through the redactor. `--debug` redacts
identifiers in its log lines only: ordinary output (`robots` prints serials) and Python tracebacks
bypass it, so review and sanitize the whole capture, not just the log, before sharing it.

## Core qualification sequence

Run in this order. Each scenario names the evidence that closes it — an observation, not an
impression.

| # | Scenario | Class | Evidence that closes it |
|---|---|---|---|
| 1 | `host-smoke` — install from the published artifact, `--version`, `robots` | W0 | version matches the RC tag; bottle/pkg provenance confirmed |
| 2 | `state-read` — `state`, `status`, `monitor` against a live robot | W1 | telemetry arrives; values plausible |
| 3 | `profile-list` — two robots saved, `robots` / `use` / `rename` | W0 | default marked, names and serials shown |
| 4 | `named-write` — a W2 command with two robots saved | W2 | the prompt **names the robot before asking**, and the named one acts |
| 5 | `saved-robot-provision` — `provision` with saved robots, choosing from the list rather than typing a serial | W4 | the picker offers the saved robots; provisioning completes against the chosen one |
| 6 | `cert-flow` — full provision from the published artifact | W4 | BLE acks: `CERT_DEVICE_CERT`, `CERT_DEVICE_KEY`, `APPLY_CONFIG committed`, `DEVICE_REBOOT`; stored files match those byte counts |
| 7 | `broker-accept` — the robot reconnects after 6 | W4 | broker logs the certificate CN as the username |
| 8 | `lease-guard` — provision on a network that leases slowly | W4 | the printed address is one the robot actually holds |
| 9 | `power-confirm` — `power` with two robots saved | W3 | the confirmation names the robot; operator recovers it physically |
| 10 | `backup-restore` — `backup` then `restore` | W0 | restored profile matches; layout marker readable |
| 11 | `ha-upgrade` — upgrade the integration over an existing install | W1 | the wifi signal sensor is present and **enabled** after upgrade |

**Scenarios 6 and 7 prove different things and must not be merged.** The broker logging
`CN=<serial>` does *not* prove the new certificate landed: a robot that already held a certificate
from an earlier run produces an identical log line if the BLE write silently failed. The write is
evidenced by the acknowledgements in 6. Distinguishing them at the broker would need the presented
certificate matched by fingerprint, which mosquitto is not configured to log.

## Failure and interruption scenarios

The two picker scenarios need a store with two robots and **no default**. Provisioning sets a
default whenever none exists, so a normal two-robot setup always has one: copy the store to a
scratch directory, point `WHISKERLESS_HOME` at the copy, delete its `default` file, and confirm
`robots` marks no robot as default before starting.

| Scenario | Class | Expected |
|---|---|---|
| `no-tty` — a W2 command, two robots saved and **no default**, stdin not a TTY | W0 | ambiguity error, non-zero exit, **no hang** |
| `decline-write` — answer no at a W2/W3 prompt | W0 | nothing sent |
| `wrong-robot` — two robots saved and **no default**; pick the second at the picker | W2 | the chosen robot acts, not the first listed |
| `abandoned-provision` — enter pairing mode, then abort | W4 | tool states the robot's WiFi is now wiped and only a completed provision restores it |
| `unreachable-broker` — provision from a host that cannot reach the broker | W4 | the error says so, rather than failing obscurely |
| `robot-asleep` — a W1 command against a robot that does not answer | W1 | distinguishable from a typo'd serial, or the limit is stated |

A skipped scenario needs a written waiver naming the reason, the residual risk, and who accepted
it. Absence of an attempt is not a pass.

## Release acceptance

An RC is eligible for stable promotion only when:

1. All normal CI jobs are green for the exact RC commit.
2. The published RC assets install and report the expected version, on the channel being qualified.
3. Every core scenario completes on real hardware, from the published artifact, with the ESP
   firmware recorded. Any RC that changes `provision`, the profile store, or the resolve/confirm
   order of a write command, or any robot-facing write path (command encoding, MQTT transport,
   settings verification, Home Assistant command delivery), must complete the **full** sequence;
   only an RC that changes none of those may run the W0/W1 subset.
4. Every failure scenario has a saved pass/fail result and no unexplained outcome.
5. No shareable report or log contains a serial, certificate, key, or WiFi password.
6. Any failure is reproduced off-hardware before a fix is accepted, whenever a deterministic seam
   can represent it.

The report is evidence about one robot on one firmware, not a universal claim.
