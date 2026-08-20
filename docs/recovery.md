# Recovery & fault handling

Everything whiskerless does is **reversible**, and the tooling refuses the
commands that could brick the unit. This guide covers going back to the cloud,
getting the robot back into pairing mode, and clearing the everyday faults.

## Go back to the Whisker cloud

Restoring stock cloud operation is re-onboarding through the official **Whisker
app**:

1. In the Whisker app, run the normal "set up / reconnect" flow for the robot.
2. The app rewrites the real Amazon root CA + AWS endpoints over the *same* BLE
   channel whiskerless used — **and reissues the robot's device certificate and
   private key**, which is what lets it authenticate to AWS again.

That's it — no flashing, nothing permanent, no fuses burned.

**This holds whether or not whiskerless replaced the robot's identity.** If you
let it issue the robot a certificate of your own, the factory one is gone — but
the app writes a fresh identity on every onboarding regardless, so the route home
is the same. That is not an assumption: a Whisker-app onboarding was captured and
decoded, and it writes all three certificate slots even to a robot that already
had a valid identity. See
[the app-onboarding capture](devices/litter-robot-4/provisioning/app-onboarding-capture.md).

The one thing that recovery therefore depends on is Whisker's app continuing to
behave this way. If they ever changed onboarding to reuse an existing identity
rather than reissue one, a robot carrying your certificate instead of theirs
would have no route back. Nothing observed suggests they intend to, and there is
no way to insure against it from here — which is why the identity write announces
itself before it happens rather than being quiet about it.

**This round trip has been done**, not just reasoned about: a robot provisioned onto
a local broker was re-onboarded through the Whisker app and returned to normal cloud
operation.

Provisioning writes six things, all of them the same ones the app writes at first
setup: the client id (set to the serial), the WiFi SSID and passphrase, the broker
host, the two topic endpoints, and the root CA — plus, if you asked for it, the
robot's own certificate and key, which the app also writes every time. Nothing there is irreplaceable —
Amazon's root CAs are public, the endpoint is Whisker's own, and the topics embed the
serial printed on the robot's own label.

**There is nothing to back up first, and no way to do it if there were.** The only
per-robot secret is the device certificate and key. whiskerless can *write* those
(that is the optional identity step), but nothing can **read** them back — the
provisioning protocol has no read verb for any certificate, which was byte-verified
from the firmware's own message descriptors. Of the config messages mapped so far, the only one that answers
with data is the device-id read (a 6-byte value we format as a MAC — one proto
comment suggests it may be the serial instead; unresolved, see the backlog's #52) —
there is no mapped way to retrieve a certificate, host or topic at all. Whether the
firmware offers a read we simply have not mapped is settled: it does not (#51). Every message type on both endpoints was read out of the firmware's own descriptor tables, and none of them is a read for certificates, endpoints or the host.

## Re-enter pairing mode (to re-provision)

> 🚨 **Entering pairing mode wipes the robot's saved WiFi, and there is no way
> back except completing a provision.** Do not enter it to "have a look".

The robot forgets its network as it enters pairing mode — that much is Whisker's
own documented behaviour. On the one unit tested (ESP 1.1.75, 2026-08-19) nothing
restored it by itself: the mode showed no sign of timing out over the half hour it
was watched, no button tried would leave it (a short Connect press toggles the WiFi
radio, a hold re-arms pairing), and the robot was off the network entirely — it did
not answer a ping even from a host on its own VLAN, and the gateway could not resolve
its MAC. Read "no way out but a provision" as that robot's behaviour rather than a
firmware-wide guarantee; plan for it either way.

This is the robot's behaviour and it affects cloud users identically — Whisker's
own page says holding Connect too long means it "has entered onboarding mode and
forgotten its saved WiFi network", recovered through the app's *Update Network*
flow. `whiskerless provision` is the same fix; it just needs a laptop in
Bluetooth range rather than a phone.

If you need to re-run `whiskerless provision` (first time, a changed broker, or
to recover from a bad config), and you are ready to finish it:

1. **Hold** the robot's **Connect** button for about three seconds, until its
   light starts **blinking yellow**. That is pairing mode: the robot is
   advertising over BLE again — and has just dropped off WiFi. **Hold it, do not
   tap it** — a short press toggles WiFi off instead (the light goes white);
   another short press brings the radio back, but does *not* leave pairing mode.
2. Run `whiskerless provision` near the robot, and complete it.

You can re-provision as many times as you like; it's the same mechanism the
Whisker app uses at onboarding. What you must not do is start and abandon it.

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
