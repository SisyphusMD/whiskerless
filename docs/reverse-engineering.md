# How the local protocol was reverse-engineered

A short writeup of how whiskerless came to be, for the curious — and so others can
build on it. None of this required opening a robot.

## Starting point: a public blank slate

The Litter-Robot 4 had essentially no public local-control prior art (most
community work targets the older LR3). But a **public firmware dump** of the LR4's
ESP32 and PIC controllers exists, with debug strings intact. That was the way in.

## What static analysis found

Disassembling the ESP firmware (Xtensa, radare2) showed that **all of the robot's
cloud identity lives in non-volatile storage**, not baked into the firmware: the
trusted root CA, the device certificate/key, the broker host, and the pub/sub
topics. The image embeds no real certificates.

More importantly, the robot exposes ESP-IDF's standard **protocomm** provisioning
service over BLE, with two vendor endpoints — `mqtt-config` and `whisker-config` —
that *rewrite* exactly those NVS values. And the provisioning security is
`no_sec, no_pop`: **no PIN, no proof-of-possession**. Any BLE client in range can
drive it.

That's the whole trick: install **your** CA into the root-CA slot, point the host
at **your** broker, and the robot trusts and connects to it — no soldering, no
UART, no reflash. Because the factory device cert/key are left untouched, it's
**fully reversible** by re-onboarding through the Whisker app.

The MQTT protobuf field numbers were recovered byte-exactly from the firmware's
protobuf-c descriptor tables, so whiskerless reproduces the app's frames without
needing a `protoc` build step.

## The wedge-and-recover saga (and the load-bearing step)

The first re-provisioning attempts **wedged the robot** — it dropped off the
network and went dark (recoverable by holding the panel *Connect* button to
re-enter pairing). Tracing the crash (a null-pointer panic in the broker
topic-builder, before any TCP connection) and then capturing the Whisker app's own
BLE session revealed the missing piece: the app runs the full Wi-Fi
provisioning **finalize** (`SetConfig` + `ApplyConfig`) as part of onboarding, and
*that* is what populates the runtime topic state. Skip it and the robot boots with
a null topic and panics.

Replicating the app's exact sequence —
`DEVICE_ID_SET → Wi-Fi SetConfig+Apply → wait → endpoints → CA → APPLY → reboot` —
worked cleanly. whiskerless ships that proven flow; see
[`provision.py`](../src/whiskerless/ble/provision.py).

## Mapping the command protocol

With a robot on a local broker, the command/telemetry layer was mapped by
read-modify-restore against the live unit: the `0xTTRRVVVV` wire format, the two
control primitives (read / write-or-macro), the nine macros, and the settings
registers — all documented in [devices/litter-robot-4/](devices/litter-robot-4/).
The ESP↔motor-controller link and the safety interlocks (pinch, cat-detect,
bonnet) live in the **PIC controller**, which is why those interlocks can't be
overridden from a command, and why the firmware is left untouched.

## Why some commands are still missing

The PIC firmware image in the public dump is **physically truncated** — it ends
partway through, and the partition that handles *inbound* action commands (power,
empty, the resets) simply isn't there. The candidate registers different analysis
passes proposed for those actions are unproven and contradict each other. Rather
than ship blind writes into the dangerous control band, whiskerless leaves those
actions out and documents the **zero-risk** way to recover them — capturing what
the Whisker app sends — in [compatibility.md](devices/litter-robot-4/compatibility.md#open-items).

## Build on it

Everything here is public so others can extend it — another Whisker robot, the
missing commands, a tighter enum map. See [CONTRIBUTING.md](../CONTRIBUTING.md).
