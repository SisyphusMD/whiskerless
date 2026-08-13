# Recovery & fault handling

Everything whiskerless does is **reversible**, and the tooling refuses the
commands that could brick the unit. This guide covers going back to the cloud,
getting the robot back into pairing mode, and clearing the everyday faults.

## Go back to the Whisker cloud

whiskerless only overwrites **connection details** — the trusted root CA, the
broker host and topics, the client id, and the WiFi credentials (the six fields
listed below, the same ones the app writes at first setup). It never touches the
factory **device certificate/key**. So restoring stock cloud operation is just
re-onboarding through the official **Whisker app**:

1. In the Whisker app, run the normal "set up / reconnect" flow for the robot.
2. The app rewrites the real Amazon root CA + AWS endpoints over the *same* BLE
   channel whiskerless used.
3. The untouched factory identity lets the robot authenticate to AWS exactly as
   before.

That's it — no flashing, nothing permanent, no fuses burned.

**This round trip has been done**, not just reasoned about: a robot provisioned onto
a local broker was re-onboarded through the Whisker app and returned to normal cloud
operation.

Provisioning writes six things, all of them the same ones the app writes at first
setup: the client id (set to the serial), the WiFi SSID and passphrase, the broker
host, the two topic endpoints, and the root CA. Nothing there is irreplaceable —
Amazon's root CAs are public, the endpoint is Whisker's own, and the topics embed the
serial printed on the robot's own label.

**There is nothing to back up first, and no way to do it if there were.** The only
per-robot secret is the factory device certificate and key, which whiskerless neither
writes nor reads. Of the config messages mapped so far, the only one that answers
with data is the device-id read (a 6-byte value we format as a MAC — one proto
comment suggests it may be the serial instead; unresolved, see the backlog's #52) —
there is no mapped way to retrieve a certificate, host or topic at all. Whether the
firmware offers a read we simply have not mapped is an open question (#51).

## Re-enter pairing mode (to re-provision)

If you need to re-run `whiskerless provision` (first time, a changed broker, or
to recover from a bad config), put the robot back into BLE pairing mode:

1. **Hold** the robot's **Connect** button — a short press does nothing — for a
   few seconds, until its light starts **pulsing yellow**. That is pairing mode:
   the robot is advertising over BLE again.
2. Run `whiskerless provision` near the robot.

You can re-provision as many times as you like; it's the same mechanism the
Whisker app uses at onboarding.

## Everyday faults & how they clear

These are normal robot behaviors, surfaced as Home Assistant entities — not
whiskerless problems.

### Cat-detected / excess-weight pause

If a cat is on the globe (or weight is detected), the robot **pauses** instead of
cycling — you'll see the **Status** sensor report a paused/cat-detected state and
the **Cat detected** binary sensor turn on. It clears itself once the cat leaves
and the wait time elapses.

A **Reset** — from the panel or the Reset button in Home Assistant — releases that
pause, exactly as pressing the button on the robot does. The cat sensor keeps
working either way, so a cat still inside re-triggers it and the robot pauses again.
Nothing bypasses the sensor itself; a reset just clears the current hold.

### Bonnet removed

Removing the bonnet trips a safety interlock (**Bonnet removed** binary sensor).
Reseat the bonnet and the robot resumes; the sensor clears on the next report.

### Globe motor fault

The **Globe motor fault** binary sensor reports the robot's own fault state
(e.g. an obstruction). Clear the obstruction and let the robot retry; power-cycle
the unit at the wall if it stays faulted. (This reflects the robot's status — it
isn't something whiskerless causes.)

## Telemetry looks silent

The robot reports **events**, so right after connecting there may simply be
nothing new to report yet. To pull a fresh snapshot on demand:

- **Home Assistant:** press the **Refresh** button (a diagnostic entity on the
  device page), or wait — the integration also polls a full state every few
  minutes.
- **CLI:** `whiskerless state` requests and prints a full state document.

Make sure your listener is subscribed *before* the robot publishes a burst — the
CLI `monitor` and the HA integration both subscribe on connect, so they catch
subsequent reports.

## "Can I brick it?"

Normal use can't. whiskerless classifies every command and **unconditionally
refuses** the brick/reset-class opcodes (reset / main-board OTA, globe-motor OTA,
flash erase, hardware reset) — there's no flag that lets them through. The clean
cycle, reset and empty cycle ship as synthesised panel button presses — writing that
register reproduces the code the panel emits, so the robot cannot tell it from a
finger, and its own interlocks apply either way. Power ships disabled and requires an
explicit override, because a robot switched off has left the network. The destructive
panel combos (factory reset, plug pull, onboarding) are refused unconditionally.
Settings writes are all reversible and verified by read-back. See
[devices/litter-robot-4/commands.md](devices/litter-robot-4/commands.md) for the
full safe-list / never-send breakdown.

If you ever do wedge a robot's config (e.g. an interrupted provision), it's
recoverable: re-enter pairing mode (above) and either re-provision or re-onboard
through the Whisker app.
