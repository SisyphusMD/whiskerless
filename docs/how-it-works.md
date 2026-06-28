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
There's no PIN. whiskerless connects to it and rewrites two things in the robot's
non-volatile storage:

1. the **trusted root CA** → your CA (so the robot trusts *your* broker), and
2. the **broker host** → your broker's address.

It deliberately does **not** touch the robot's factory client certificate/key, so
the change is **fully reversible** — re-onboarding through the Whisker app puts
the stock CA and cloud endpoint back. See [reverse-engineering.md](reverse-engineering.md)
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

Yes, by construction. The only commands that move the motor (a clean cycle) or
could harm the robot are gated by a safety layer that **refuses brick/reset-class
commands outright** — see [devices/litter-robot-4/commands.md](devices/litter-robot-4/commands.md).
The robot's own hardware interlocks (pinch, cat-detect, bonnet) live in a
separate controller and can't be overridden by any command.
