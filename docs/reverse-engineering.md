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

## The action commands: how three of five were found

For most of this project's life nothing could make the robot *act* — every command
was a setting. The hunt assumed the triggers were **macro opcodes** in the `0xA0`
range, because that is where the firmware brief put them, and `cleanCycle` was
mapped to `0xA3`.

They were never opcodes. `0x01` is the **panel button register**, it accepts writes,
and writing the code the robot emits for a button synthesises that press. The clean
cycle is `0x02010201`; reset is `0x02010401`. Both live-proven on 2026-08-09.

The data had been sitting in every capture for months — the robot publishes
`0x010201` each time someone presses Cycle. It was read as telemetry rather than as
a writable register, and the search stayed in a range that never contained the
answer. Two corrections unlocked it: learning that every write is echoed back with
the register's post-write value (which turns a blind write into a measurable
experiment), and discarding the claim that an unrecognised write reaches an
arbitrary PIC register (which had made the cheap test look reckless).

**Still missing: `powerOn`/`powerOff` and `emptyCycle`.** Both ARE panel buttons, so
`0x01` is the obvious route; their codes simply have not been captured. Watching that
register while pressing the physical button costs nothing and is the whole job. The
waste-drawer reset is not separate — a Reset press performs it when the full flag is
set.

### `0xA3` is not the clean cycle (and what it *is* was never established)

Early on, `0x02A30000` was taken to be the clean-cycle trigger — it's the byte the
cloud's `cleanCycle` verb appears to map to, and sending it *looked* like it started
a cycle. It isn't the cycle: the real trigger is `0x02010201`, a synthesized Cycle
button press, live-proven twice (see below).

What `0xA3` actually does is **unresolved**. One send on ESP 1.1.75 was followed by
`odometerPowerCycles` incrementing while `odometerCleanCycles` stayed flat, which
reads as a reboot, and the apparent "clean cycle" was then the robot's automatic
first-cycle-after-power-on. That is a real observation, but it is **one trial with no
replication**, and this unit has since produced spontaneous reboots, a wifi drop and
a latched sensor on its own. A coincident reboot cannot be excluded.

It stays **never-send** anyway, and the reason is cost, not proof: there is nothing
to gain from sending it now that the cycle and reset are both reachable through
`0x01`, and if the reboot reading is right the downside is real. Refusing an opcode
we have no use for costs nothing; being wrong about one that may orchestrate a
main-board OTA does not. Nobody should re-test this to settle it.

### The triggers live in firmware no public image contains

The motor and power logic runs on the main board's **PIC18F67K40**; the ESP just
forwards each `0x02RRVVVV` over UART. Disassembling the largest public OTA image
(`LR4_2910_0A00_0247`, 126 KB) recovers the raw UART receive code — but not the
command parser or action **dispatch** it feeds. That image is itself **truncated
mid-application at `0x1EDB6`**: the receive fragments it contains have no in-image
callers, and the loop that sequences the 7-byte frame, the register→action dispatch
table, and the response-frame builder all sit above the cut — in the ~832-byte
application tail (`0x1EDB6–0x1F0F6`) and the ~3.8 KB **bootloader** (`0x1F0F6+`, the
reset-vector target), both **factory-flashed and never shipped in any OTA image**. So
the bytes that map cleanCycle / power / empty / reset to motor actions are physically
absent from *every* public image. The candidate registers earlier passes
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

1. **Capture the robot's own reports (zero hardware, zero risk).** Watch the local
   `activity` topic on a whiskerless-provisioned robot and press one physical panel
   button at a time, noting the wall-clock time so each event can be tied to the
   action. Register `0x01` (panel button events) was found exactly this way. Pair it
   with *Download diagnostics* from Home Assistant's `litterrobot` integration on a
   robot still on the cloud, which supplies Whisker's field names and enum vocabulary.
   This is the contributor path; see
   [compatibility.md](devices/litter-robot-4/compatibility.md#open-items).
   Sniffing the cloud's own command bytes is not available *at this tier*: a
   cloud-paired robot talks to Whisker's AWS broker using a factory device key that
   provisioning never touches. It becomes available once the ESP flash read below
   yields that identity, at which point a client can subscribe as the robot — which
   is one of the strongest reasons to want the dump.
2. **Decompile the Whisker app (Blutter).** It confirms the full command **verb**
   set (which actions exist — e.g. `emptyCycle`, drawer reset) even though the
   verb→byte mapping is server-side, so it bounds what we're still looking for.
3. **Dump your own unit's firmware.** An **ESP32 flash read** (`esptool read_flash`)
   is the preferred route: it yields the `pic_factory` partition — the *complete*
   factory PIC image, bootloader included — plus the device's AWS certs, and it's
   non-destructive and bypasses PIC code-protection. A **PIC ICSP dump** via the
   documented programming header is the alternative (chip = PIC18F67K40; header pins
   MCLR/VPP · ICSPCLK · ICSPDAT · GND, power from the 15 V adapter).

A captured activity record tying a physical action to its `0xRRVVVV` chips away at
these; a genuine write code closes one out. Share either via the "Protocol finding"
issue template and it ships.

## Build on it

Everything here is public so others can extend it — another Whisker robot, the
missing commands, a tighter enum map. See [CONTRIBUTING.md](../CONTRIBUTING.md).
