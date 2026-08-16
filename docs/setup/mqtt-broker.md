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

Three consequences:

- The broker must present a **server certificate the robot trusts** — that's the
  whole point of [certificates.md](certificates.md). Set that up first (or
  alongside this).
- The robot must be on a network that can **reach the broker's IP on port 8883**.
  Putting the robot and broker on the same IoT VLAN/subnet is the simplest setup.
- **The broker must listen on 8883.** The port is not provisionable and not
  configurable: it is a compile-time constant in the firmware, loaded at exactly one
  place, and 443 and 1883 appear nowhere in the image. Only the *host* is written
  during provisioning. (whiskerless's own `--port` is unrelated — that is the CLI's
  connection to your broker, not the robot's.)
- **The robot cannot log in with a username and password.** There is no field for
  one anywhere: not in the provisioning schema, not among the NVS keys the
  provisioning component persists, and not as a string in the firmware. It was built
  for AWS IoT, which authenticates clients by certificate, and
  provisioning writes only the CA it should *trust* — its own client certificate
  and key are Whisker's, are never touched, and are signed by a CA you do not
  have, so you cannot validate them either. A listener that demands a password
  therefore locks the robot out, and one that demands a client certificate
  rejects the one it presents. **The robot's listener has to be anonymous.**

  That is a limit on the *robot's* listener, not on your broker. Any login
  whiskerless or Home Assistant uses is a separate client on a separate,
  authenticated listener — see [below](#keeping-a-separate-authenticated-listener-for-home-assistant),
  which is the recommended shape for exactly this reason.

> **If you cannot give the robot an anonymous listener, you cannot use that broker.**
> This is the one hard requirement in the whole project. A managed or hosted broker
> you do not control, or one whose policy forbids anonymous clients outright, has no
> workaround available from this side: the robot has nothing to authenticate *with*.
> Run your own Mosquitto for the robot instead — it can be a second listener on the
> broker you already have, or a second instance on the same box.

**Ports are a convention, not a policy.** 1883 and 8883 are the registered ports for
plain MQTT and MQTT-over-TLS, and that is *all* they mean — neither one implies
anything about authentication. The split used here (authenticated on 1883, anonymous
on 8883) is a choice made in the config file below, not a property of the numbers, and
a broker is free to demand a password on 8883 and allow anonymous on 1883. What makes
the split work is `per_listener_settings true`: without it, `allow_anonymous` is a
single global setting, so adding the robot's listener to an authenticated broker either
locks the robot out or opens the whole broker.

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

Since the robot's listener cannot ask for a password, an ACL is the hardening that
fits it: it bounds what an anonymous client on that listener may touch, without
asking it for credentials it has no way to send. If you'd like the anonymous
listener to only reach the robot's topics, add an ACL file:

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
