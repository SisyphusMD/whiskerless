# How it works

whiskerless makes a Litter-Robot 4 talk to **your** MQTT broker instead of
Whisker's cloud — once, over Bluetooth, and then forever after over your network.
The robot keeps its own firmware; you only change *which broker it trusts and
connects to*.

```
  ┌─ one-time, on the bench (BLE) ───────────────────────────────────────────┐
  │  your computer ──protocomm──► robot:  install YOUR CA  (root-CA slot)     │
  │                                       set broker host = your-broker       │
  │                                       keep the prod/LR4/<serial>/… topics  │
  │                                       commit + reboot                      │
  └──────────────────────────────────────────────────────────────────────────┘
                                   │
  ┌─ every day after (MQTT/TLS) ───▼──────────────────────────────────────────┐
  │  robot ──MQTT over TLS :8883──► your broker ──► whiskerless / Home Assistant│
  │     publishes  prod/LR4/<serial>/state   (full state document)             │
  │                prod/LR4/<serial>/activity (live telemetry)                 │
  │     subscribes prod/LR4/<serial>/command (your commands)                   │
  └────────────────────────────────────────────────────────────────────────────┘
```

## The one-time BLE step

The robot runs ESP-IDF and exposes its standard **protocomm** provisioning
service over Bluetooth — the same mechanism the Whisker app uses to onboard it.
There's no PIN. whiskerless connects to it and rewrites the robot's connection
details in its non-volatile storage — the same six fields the app writes at
first setup:

1. the **trusted root CA** → your CA (so the robot trusts *your* broker),
2. the **broker host** and its two **topic endpoints** → your broker,
3. the **client id** (set to the serial), and the **WiFi credentials**.

Since 0.2.0 it also writes the robot a **client certificate of its own**, signed
by your CA, over the same link — so the broker can require one and know which
robot is talking. The change stays **fully reversible**: re-onboarding through the
Whisker app puts the stock CA, certificate and cloud endpoint back. See [reverse-engineering.md](reverse-engineering.md)
for how this was worked out, and [setup/](setup/) to do it.

## Every day after

Once re-provisioned, the robot connects to your broker over **MQTT/TLS on port
8883**, authenticating the broker against your CA. It then speaks the same plain
JSON it always did: a full state document on demand, a live telemetry stream, and
a command topic it listens on. whiskerless and the Home Assistant integration
just subscribe and publish — the protocol is documented in
[devices/litter-robot-4/protocol.md](devices/litter-robot-4/protocol.md).

## What you gain (and one thing you give up)

- **Local + private** — no cloud account, no internet round-trip, nothing to
  rate-limit or block.
- **Fast** — state changes arrive as a push, not a poll.
- **No forced updates** — the robot receives firmware over AWS IoT *Jobs*, which
  a local broker never sends. Your robot stays on its current firmware. That's a
  feature for stability; the trade-off is you don't get Whisker's OTA updates
  while local. To update, temporarily re-onboard to the Whisker app, then
  re-provision back. See [recovery.md](recovery.md).

## Is it safe?

Yes, by construction. Every command is classified before it can reach the wire, and
the brick/reset-class opcodes plus the destructive panel combos (factory reset, plug
pull, onboarding) are **refused outright, with no override** — see
[devices/litter-robot-4/commands.md](devices/litter-robot-4/commands.md).

The actions that move the globe are not special-cased, because they are not special:
whiskerless runs a clean cycle by writing the same code the panel emits when you press
Cycle, so the robot receives an ordinary button press. The hardware interlocks (pinch,
cat-detect, bonnet) live in a separate controller and can't be overridden by any
command, whether it came from your finger or your automation.
