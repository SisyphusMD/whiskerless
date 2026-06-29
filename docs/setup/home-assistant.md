# Home Assistant integration

The Whiskerless integration is **fully local** and **push-first** — entities
update the instant the robot reports, with no cloud and no polling lag. It rides
on Home Assistant's own **MQTT integration**, so there's nothing to configure
beyond clicking *Add* on each robot as it's discovered.

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

## Entities you get

**Sensors**

- **Status** — Ready / Clean cycle / Cat detected / etc.
- **Litter level** (%) and **Litter level distance** (mm, diagnostic, disabled by default)
- **Waste drawer level** (%)
- **Pet weight** (lb)
- **Clean cycle count** (diagnostic)
- **Wi-Fi signal** (dBm, diagnostic, disabled by default)

**Binary sensors**

- **Cat detected** (occupancy)
- **Waste drawer full** (problem)
- **Bonnet removed** (problem)
- **Globe motor fault** (problem)

**Controls**

- **Night light** (select: off / on / auto) and **Night light brightness** (number)
- **Clean cycle wait time** (select)
- **Control lock**, **Panel sleep mode**, **Weekday sleep schedule** (switches)
- **Panel sleep time** / **Panel wake time** (time entities)

Settings writes are verified by reading them back, and the schedule times retry
automatically (the robot commits those with a little latency).

## What's *not* exposed

There are **no action buttons** (clean cycle, empty cycle, power, resets). Their
exact commands couldn't be verified safely from the firmware — the byte once mapped
to "clean cycle" was proven on a live robot to reset the unit, not run a cycle — so
they're intentionally left out rather than shipped as risky guesses. See
[../devices/litter-robot-4/compatibility.md](../devices/litter-robot-4/compatibility.md).

## Troubleshooting

- **The robot never appears to add:** confirm Home Assistant's **MQTT
  integration** is connected to the broker, and that the robot actually
  re-provisioned onto that broker (you should see it connect in the broker log,
  or its messages under `prod/LR4/<serial>/#`). The robot must publish at least
  once to be discovered — use it once if needed.
- **Entities show *unavailable* after adding:** the robot is event-driven and may
  not have published recently. Enable and press the **Refresh** button (a
  diagnostic entity), or wait for the next report. The integration also re-asks
  for a full state every few minutes as a safety net.
