# How the local protocol was reverse-engineered

A short writeup of how whiskerless came to be, for the curious — and so others can
build on it. None of this required opening a robot.

## Starting point: a public blank slate

The Litter-Robot 4 had essentially no public local-control prior art (most
community work targets the older LR3). But **public firmware images** of the LR4's
ESP32 app and its PIC main-board OTA exist, with debug strings intact. That was the
way in — though, as the [last section](#the-action-commands-why-theyre-still-missing)
explains, those OTA images are app-region only and omit the bootloader where the
inbound action dispatch lives.

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

## The action commands: why they're still missing

whiskerless exposes everything on the **safe surface** — reads, the report macros,
and the settings registers — all proven by live read-modify-restore. What it does
**not** expose is any command that drives the globe or changes power state:
`cleanCycle`, `powerOn`/`powerOff`, `emptyCycle`, and the panel/drawer resets. Here
is the honest state of that hunt.

### `0xA3` is a reset, not a clean cycle (live-proven)

Early on, `0x02A30000` was taken to be the clean-cycle trigger — it's the byte the
cloud's `cleanCycle` verb appears to map to, and pressing it *looked* like it
started a cycle. It does not. Captured live on a robot running **ESP fw 1.1.75**:
sending `0x02A30000` **rebooted the unit** — `odometerPowerCycles` incremented while
`odometerCleanCycles` stayed flat. The "clean cycle" people saw was the robot's
**automatic first-cycle-after-power-on**, not a commanded one. So `0xA3` is the
**reset / main-board-OTA orchestrator** (it reboots, or no-ops), and it's now
classified never-send. The real cleanCycle trigger is unknown, and the
clean-cycle button / CLI command / library builder were removed rather than left
shipping a reset disguised as a cycle.

### The triggers live in firmware no public image contains

The motor and power logic runs on the main board's **PIC18F67K40**; the ESP just
forwards each `0x02RRVVVV` over UART. Disassembling the largest public OTA image
(`LR4_2910_0A00_0247`, 126 KB) recovers the inbound UART parser — but the action
**dispatch** it calls funnels through a linker trampoline
(`CALL 0x02536 → GOTO 0x1EC16`) into the top ~3.8 KB **bootloader** region
(`0x1F0F6+`). That region is **factory-flashed and never shipped in an OTA image**,
so the bytes that map cleanCycle / power / empty / reset to motor actions are
physically absent from *every* public image. The candidate registers earlier passes
proposed are unproven and contradict each other (three different registers were
floated for "power" alone) — exactly the dangerous control-band writes the safety
guard refuses.

### We searched the whole internet for a complete dump — there isn't one

A complete image (one that includes the bootloader / the factory PIC) would close
this out. So we looked, exhaustively: GitHub and its forks, GitLab, the file-shares
(mega / drive / mediafire / pastebin), search-engine dorks, and the exact OTA
filenames as mirror-finders; the non-English reverse-engineering communities
(Chinese 52pojie / kanxue / CSDN, Russian 4pda, German mikrocontroller); security
research (CVE / CTF / conference talks); the repair and smart-home communities
(Reddit, iFixit, Hackaday, YouTube); cross-device leakage from the LR3; and the
Internet Archive. **No complete public dump of the LR4 exists.** The community's own
active main-board thread confirms it — people with dead units *intend* to dump them;
none has been shared. Every public artifact is an app-region OTA blob, never the
bootloader.

### What it will take (and what's next)

The missing dispatch has to be **captured or dumped**, not downloaded. In rough
order of effort:

1. **Capture the cloud's bytes (zero hardware, zero risk).** Subscribe to *your own*
   broker's `prod/LR4/<serial>/command` topic while the robot is still cloud-paired
   (or a second robot is) and press the action in the Whisker app. The cloud
   publishes the literal `{"serial","data":["0x02RRVVVV"]}` — that hands you the
   register+value at PROVEN confidence. This is the contributor path; see
   [compatibility.md](devices/litter-robot-4/compatibility.md#open-items).
2. **Decompile the Whisker app (Blutter).** It confirms the full command **verb**
   set (which actions exist — e.g. `emptyCycle`, drawer reset) even though the
   verb→byte mapping is server-side, so it bounds what we're still looking for.
3. **Dump your own unit's firmware.** An **ESP32 flash read** (`esptool read_flash`)
   is the preferred route: it yields the `pic_factory` partition — the *complete*
   factory PIC image, bootloader included — plus the device's AWS certs, and it's
   non-destructive and bypasses PIC code-protection. A **PIC ICSP dump** via the
   documented programming header is the alternative (chip = PIC18F67K40; header pins
   MCLR/VPP · ICSPCLK · ICSPDAT · GND, power from the 15 V adapter).

Any one captured `0x02RRVVVV` closes one of these out. Share it via the "Protocol
finding" issue template and it ships.

## Build on it

Everything here is public so others can extend it — another Whisker robot, the
missing commands, a tighter enum map. See [CONTRIBUTING.md](../CONTRIBUTING.md).
