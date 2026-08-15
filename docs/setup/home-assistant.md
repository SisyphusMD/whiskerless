# Home Assistant integration

The Whiskerless integration is **fully local** and **push-first** — entities
update the instant the robot reports, with no cloud and no polling lag. It rides
on Home Assistant's own **MQTT integration**, so there's nothing to configure
beyond clicking *Add* on each robot as it's discovered.

## Supported devices

The **Whisker Litter-Robot 4**, and only that model. The protocol was recovered
from ESP firmware **1.1.65**, validated live on **1.1.75**, and independently
confirmed on **1.4.4** by a two-week field capture; the settings, state and
activity surfaces are identical across all three. The optional **LitterHopper**
attachment is supported and detected automatically — the hopper work came from
that 1.4.4 install.

Litter-Robot 3 and earlier speak a different protocol entirely and are not
supported. Firmware caveats and the per-opcode differences are in
[../devices/litter-robot-4/compatibility.md](../devices/litter-robot-4/compatibility.md).

## Prerequisites

1. The **MQTT integration** set up in Home Assistant and connected to your
   broker (e.g. the Mosquitto add-on, or any broker — Settings → Devices &
   Services → Add Integration → MQTT). This is the broker your robots publish to.
2. A broker the robot can reach over TLS → [mqtt-broker.md](mqtt-broker.md) and
   [certificates.md](certificates.md).
3. The robot re-provisioned onto that broker → `whiskerless provision`.

> The robot always connects to the broker over TLS on 8883 with your CA. Home
> Assistant's MQTT integration connects to the *same* broker however you like
> (commonly a local `1883` listener with a username/password) — the two are
> independent, and Whiskerless simply reads the robot's messages through HA's
> connection.

## Install via HACS

1. In Home Assistant, open **HACS** → the **⋮** menu → **Custom repositories**.
2. Add `https://github.com/SisyphusMD/whiskerless` with category **Integration**.
3. Install **Whiskerless**, then **restart Home Assistant**.

### Release candidates

Before a release ships, a candidate goes out as a GitHub *prerelease* so it can be
run on real hardware first. It never becomes "latest", so you only get one on
purpose: in HACS open Whiskerless → **⋮** → **Redownload** → enable **Show beta
versions**, and pick the `-rc.N` build. Turn the toggle back off to return to
stable releases. That only hides prereleases from the picker, so to actually go
back, **Redownload** again, choose the newest stable version, and restart Home
Assistant.

## Add a robot (it discovers itself)

There's nothing to type. When a re-provisioned robot publishes to your broker,
it shows up under **Settings → Devices & Services** as a **Discovered** device:

1. You'll see **"Whiskerless — Litter-Robot 4 (LR4Cxxxxxx)"** with **Add** / **Ignore**.
2. Click **Add**, give the robot a **name** (e.g. *Upstairs litterbox*), and submit.

That's it — the device and all its entities are created. **Ignore** hides a robot
you don't want.

> A freshly-provisioned robot appears the next time it reports. Telemetry is
> event-driven, so it may take a couple of minutes (or trigger it by using the
> robot). Whiskerless asks the robot for a full state the moment it's added.

## Naming, and renaming later

The name you choose when adding the robot becomes the **device name**, and the
entity IDs are generated from it — so naming it *Upstairs litterbox* gives you
`sensor.upstairs_litterbox_waste_drawer_level`, and so on. With several robots,
naming each one at add time keeps their entities cleanly separated.

If you rename the device later (device page → ✏️), Home Assistant offers to
**update the entity IDs** to match. That works for entities still using their
generated IDs; if you've already hand-customized some entity IDs, those
particular ones may need a manual rename ([frontend #19635](https://github.com/home-assistant/frontend/issues/19635)).
Naming at add time avoids the whole question.

## Multiple robots

Just provision each robot — they each appear to **Add** on their own. **No
re-setup, no broker details, no serial to type.** One, two, or four robots all
work the same way; each becomes its own device.

## Data updates

Whiskerless is **push**. It subscribes to the robot's own MQTT topics through
Home Assistant's MQTT integration and updates entities the moment a message
arrives — there is no polling interval to tune and no cloud round-trip.

The robot reports on its own events (a cat visit, a cycle, a settings change),
so a robot nobody has used may stay quiet for a long time. Three things cover
that:

- Whiskerless asks for a **full state document** the moment a robot is added.
- A **long heartbeat** re-asks periodically. It is not a polling loop for fresh
  values — it exists only to notice a robot that has stopped answering, which
  marks its entities unavailable.
- The **Refresh** button (a diagnostic entity on the device page) requests a
  state document on demand. Home Assistant's own
  `homeassistant.update_entity` action does the same thing if you'd rather call
  it from an automation.

Writes are not trusted blind. Settings registers commit with variable latency, so
every write is followed by a read-back and retried if the robot has not taken it
yet — that is why a slider occasionally snaps back to its old value for a moment
before settling.

## Entities you get

**Sensors**

- **Status** — Ready / Clean cycle / Cat detected / etc.
- **Litter level** (%) and **Litter level distance** (mm, diagnostic, disabled by default)
- **Waste drawer level** (%)
- **Pet weight** (lb)
- **Last cat visit**, and **Last visit duration** (not every robot reports one; enables itself)
- **Waste drawer last moved**
- **Clean cycle count** (diagnostic)
- **Litter reference** (diagnostic)
- **Wi-Fi signal** (dBm, diagnostic, disabled by default)

**Binary sensors**

- **Cat detected** (occupancy)
- **Waste drawer full** (problem)
- **Bonnet removed** (problem)
- **Globe motor fault** (problem)
- **Excess weight** (problem) — something has sat on the scale for over 30 minutes,
  which blocks cycling; the robot shows it only on the panel
- **Panel sleep mode** (diagnostic) — whether the panel is asleep right now; set it
  via the weekday schedule below, the firmware refuses direct writes

**Controls**

- **Night light** (select: off / on / auto) and **Night light brightness** (number)
- **Clean cycle wait time** (number, 3–30 minutes)
- **Panel brightness (bright room)** / **(dark room)** (numbers) — High/Low name the
  ambient light level, not the brightness rank
- **Control lock**, **Weekday sleep schedule** (switches)
- **Panel sleep time** / **Panel wake time** (time entities)

**Calibrating the litter percentage**

`litterLevel` is a *distance*, and there is no universal distance-to-percent
curve: the cloud measures against a reference calibrated per robot
(`optimalLitterLevel`) that simply is not in the local state document, and
measured references differ by ~10 mm between robots — enough to move the answer
by 15 points.

**It calibrates itself over time.** The integration watches what your robot
reports and learns the *fullest* reading it has seen, then treats that as "about
a full fill" — the same 90% anchor the button below sets, just reached without
you. It deliberately does not guess the empty end: a robot in ordinary use never
bares its globe, so the emptiest reading seen is not 0% and pretending otherwise
would report "empty" on a normal day.

It only samples a settled robot (no cat on the scale, not mid-cycle, status
ready), discards readings no litter surface could produce, and needs a second
reading to confirm a new extreme. The hopper is learned the same way, except its
floor must be hit across several separate dispenses before it counts as empty —
which is why **Hopper level (%)** stays unknown for a while, and why **Hopper out
of litter** stays quietly off until your robot's own floor is known (floors differ
per unit, so a fixed threshold would cry empty on some robots while litter still
flowed).

If you want it right immediately rather than eventually, measure it yourself:

1. Fill the globe the way you consider full. Nothing here knows what your
   robot's markings look like, and it does not need to: whatever level you pick
   becomes 90%, so pick the one you would call a fresh fill.
2. Enable the calibration buttons — they ship disabled, because the robot
   learns its own scale and a press at the wrong moment pins the percentage to a
   wrong number for good. Device page → the two `Calibrate …` entities → enable.
3. Press **Calibrate full** (a config button on the device page) with the robot
   idle and empty — no cat in it, no cycle running.

**How you know it worked:** the **Litter reference** sensor (diagnostic) changes
to the millimetre reading it just captured. If your firmware does not publish its
own percentage, **Litter level** moves to 90% at the same moment; on firmware that
does, the robot's own figure keeps winning and the reference is stored for later.
A press the robot cannot answer fails loudly rather than silently — see below.

That reading becomes 90%, matching how the cloud pins "at optimal" and leaving
headroom above for an overfill. If you ever have the globe empty, press
**Calibrate empty** too — a second point replaces the assumed
slope with a true two-point scale. It is genuinely optional; nobody should empty
a litter box for a dashboard number.

Calibration is refused mid-cycle: the sensors are pointed at the rotating globe
then, and capturing that would bake in a meaningless reference.

**LitterHopper (optional hardware)**

The hopper is invisible in the local state document — every hopper fact comes
from the activity stream — so these five entities ship **disabled** rather than
reading unknown forever on the robots that don't have one:

- **Hopper** (connected), **Hopper out of litter**, **Hopper level (%)**,
  **Hopper reading**, **Last hopper dispense**

**You don't need to do anything.** The first time your robot dispenses litter they
enable themselves and come up carrying that reading. Detection is remembered, so
they stay enabled. If you turn one off by hand it stays off.

Dispensing is what proves a hopper because nothing else can. The link register
looked like an answer for months, until a narrated session produced healthy
readings from it with the hopper sitting on a bench, and its "disconnected" code
from merely opening the hopper's drawer to refill it. So **Hopper** reports
connected once litter has actually been delivered and never reports disconnected —
there is no signal for that. A robot topped up to its target can go days without
dispensing, which is why the level is remembered across restarts rather than
falling back to unknown.

**Two entities that may not behave the way you expect**

**Last visit duration** is not reported by every robot, so it ships **disabled** and
switches itself on the first time yours reports one — exactly like the hopper
entities above, and for the same reason. This was thought to be a firmware split,
1.4.4 emitting it and 1.1.75 never doing so. It isn't: two robots on the *same*
1.1.75 build sit either side of it, one reporting a duration at the end of every
visit and the other having never emitted one. Whatever decides it, the firmware
version isn't it.

**You don't need to do anything here either.** If your robot reports durations, the
next cat enables the entity carrying that first reading. If it doesn't, the entity
stays out of your way instead of sitting unknown forever.

**Cat detected can stay on long after the cat has gone,** sometimes for hours. The
robot reports occupancy from the scale underneath, not from the sensors that look
into the globe, and it holds that report while it believes weight is still on the
scale. A 12-hour capture spent 29% of its time reporting a cat while the distance
sensors read an ordinary, undisturbed litter bed. If you automate on this entity,
treat it as "the robot is busy with a cat" rather than "there is a cat in the box
right now" — and note that the litter percentage deliberately does not sample
while it is on.

Settings writes are verified by reading them back, and the schedule times retry
automatically (the robot commits those with a little latency).

## What people use it for

- **Never discover a full drawer the hard way** — alert on *Waste drawer full*,
  or on *Waste drawer level* crossing a threshold, days before it matters.
- **Track a cat's weight without a scale.** On robots that report weights, a visit
  long enough to settle the scale reports one, which over time is a real weight
  trend — often the earliest signal of several feline illnesses. Not every robot
  does (one live unit has never emitted a weight across days of visits — the
  entity enables itself on your robot's first), and short hop-throughs report no
  weight either, so *Pet weight* holds its previous reading; trigger on it
  changing rather than on a cat arriving.
- **Notice a sick cat by their bathroom habits** — *Last cat visit* and *Last
  visit duration* make "hasn't gone in 18 hours" or "six visits in an hour" into
  automatable facts.
- **Catch faults while they're cheap** — *Globe motor fault* and *Bonnet
  removed* alert you instead of the robot quietly sitting paused.
- **Fit the box to the household** — schedule the night light and the panel
  sleep window, drop the panel brightness at night, or lock the keypad so a
  toddler or a curious cat can't start a cycle.
- **Keep working when the internet doesn't.** Everything above runs on your LAN,
  so an ISP outage or a Whisker service incident changes nothing.

Ready-to-copy automations and dashboard cards are in
[`examples/litter-robot-4/`](../../examples/litter-robot-4/) — drawer-full
alerts, fault alerts, weight logging, and night-light scheduling.

## What's *not* exposed

**Clean cycle** and **Reset** are available as buttons. **Empty cycle** and
**Power** exist too but ship **disabled by default** — enable them in the entity
settings if you want them. Both carry `(danger)` in their name: an empty cycle dumps
the whole globe into the waste drawer, and Power *toggles*, so a robot switched off
this way leaves the network and only a physical press brings it back. Home Assistant
has no confirmation prompt for a button press, so treat them accordingly.

**The filter-change wizard cannot be started remotely.** Its panel chord is a long
press, and the robot performs short presses over MQTT while declining long ones. Use
the panel for that one. See
[../devices/litter-robot-4/compatibility.md](../devices/litter-robot-4/compatibility.md).

## Removing the integration

Removing the integration is ordinary — it only undoes the Home Assistant half.
Provisioning changed the robot itself (its trusted CA and its broker), and that
stays until you change it back:

1. **Settings → Devices & Services → Whiskerless**, then the **⋮** on the robot's
   entry → **Delete**. That removes the device and all of its entities. Repeat
   per robot if you added several.
2. To remove the code as well, uninstall **Whiskerless** in **HACS** and restart
   Home Assistant.

Two things worth knowing:

- **The robot keeps publishing.** Deleting the entry only stops Home Assistant
  listening; the robot is still provisioned onto your broker and still sends
  state and activity messages. It will be offered as a *discovered* device again
  the next time it reports — choose **Ignore** if you want it to stay quiet.
- **Removal does not put the robot back on Whisker's cloud.** That is a separate,
  deliberate step: re-provision it to the Whisker app →
  [../recovery.md](../recovery.md).

## Troubleshooting

- **The robot never appears to add:** confirm Home Assistant's **MQTT
  integration** is connected to the broker, and that the robot actually
  re-provisioned onto that broker (you should see it connect in the broker log,
  or its messages under `prod/LR4/<serial>/#`). The robot must publish at least
  once to be discovered — use it once if needed.
- **Entities show *unavailable* after adding:** the robot is event-driven and may
  not have published recently. Press the **Refresh** button (a
  diagnostic entity), or wait for the next report. The integration also re-asks
  for a full state every few minutes as a safety net.
