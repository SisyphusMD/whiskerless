# Setting up the MQTT broker

whiskerless points your Litter-Robot 4 at an MQTT broker **you** run, instead of
Whisker's cloud. This guide stands up a minimal broker the robot can reach.

You don't need anything fancy — a single [Mosquitto](https://mosquitto.org/)
instance on a Raspberry Pi, a NAS, a container, or the machine that runs Home
Assistant is plenty. **If you already run Mosquitto for Home Assistant, you can
reuse it** — just add the TLS listener described below.

## What the robot expects

After re-provisioning, the robot connects exactly the way it did to the cloud,
only to your broker:

| Property | Value |
|---|---|
| Transport | **MQTT over TLS** |
| Port | **8883** |
| Client ID | the robot's **serial** (e.g. `LR4Cxxxxxx`) |
| Publishes to | `prod/LR4/<serial>/state` and `prod/LR4/<serial>/activity` |
| Subscribes to | `prod/LR4/<serial>/command` |
| Auth | TLS server-trust only (it presents its factory client cert) |

Two consequences:

- The broker must present a **server certificate the robot trusts** — that's the
  whole point of [certificates.md](certificates.md). Set that up first (or
  alongside this).
- The robot must be on a network that can **reach the broker's IP on port 8883**.
  Putting the robot and broker on the same IoT VLAN/subnet is the simplest setup.

## Minimal `mosquitto.conf`

This adds an **anonymous, TLS** listener on 8883. The robot still sends its
factory client certificate, but the broker ignores it (`require_certificate
false`), so you never have to extract or forge it.

```conf
# Anonymous TLS listener for the Litter-Robot.
listener 8883
allow_anonymous true

# Your CA + server cert/key (see certificates.md).
cafile   /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile  /mosquitto/certs/server.key

# The robot presents its factory client cert; we don't validate it.
require_certificate false
```

Start it:

```bash
mosquitto -c /path/to/mosquitto.conf -v
```

## Keeping a separate, authenticated listener for Home Assistant

It's good practice to keep the robot's anonymous 8883 listener separate from a
password-protected listener that Home Assistant (or other clients) use. Mosquitto
allows per-listener settings:

```conf
per_listener_settings true

# Authenticated listener for your own clients (Home Assistant, etc.).
listener 1883
allow_anonymous false
password_file /mosquitto/passwd

# Anonymous TLS listener for the robot.
listener 8883
allow_anonymous true
cafile   /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile  /mosquitto/certs/server.key
require_certificate false
```

Create a password for an HA user with:

```bash
mosquitto_passwd -c /mosquitto/passwd homeassistant
```

> **Reusing an existing broker:** if you already run Mosquitto, you don't need a
> second instance — just add the `listener 8883 … require_certificate false`
> block (and `per_listener_settings true`) to your existing config and reload. A
> message the robot publishes on 8883 is visible to your other clients on 1883
> because it's the same broker.

## Restrict the robot to its own topics (optional)

If you'd like the anonymous listener to only touch the robot's topics, add an
ACL file:

```conf
# in mosquitto.conf
acl_file /mosquitto/acl
```

```conf
# /mosquitto/acl
pattern readwrite prod/LR4/#
```

## Next steps

1. Generate the CA + server cert → [certificates.md](certificates.md).
2. Re-provision the robot onto this broker → `whiskerless provision` (see the
   project README).
3. Connect Home Assistant → [home-assistant.md](home-assistant.md).
