# Setting up the MQTT broker

whiskerless connects a supported robot to an MQTT broker **you** run.

You don't need anything fancy — a single [Mosquitto](https://mosquitto.org/)
instance on a Raspberry Pi, a NAS, a container, or the machine that runs Home
Assistant is plenty. **If you already run Mosquitto for Home Assistant, you can
reuse it**. On Home Assistant OS, follow
[Use the official Mosquitto broker app](#use-the-official-mosquitto-broker-app).

## Use the official Mosquitto broker app

Set this up once per household. Home Assistant keeps its usual MQTT login on port
1883. On port 8883 the same broker accepts supported robots with a client
certificate signed by the CA used during provisioning (`mutual`, the default,
or `supplied` authentication in whiskerless). Trust only a CA dedicated
to clients allowed on this broker. With externally issued client certificates,
give each client its own certificate with a unique common name.

1. **Check port 8883 first.** Open **Settings → Apps → Mosquitto broker → Log**.
   If startup says `Certificates found: SSL is available`, the app already
   creates a TLS listener on 8883. Adding another would prevent it from starting.
   To keep that listener, one option is a
   [broker on another host](#requiring-certificates-instead-recommended) for the
   robots. Continue below if startup says `SSL is not enabled` and 8883 is free
   of other listeners on the broker host.
   On the **Configuration** tab, look under **Network**. The **Normal MQTT with
   SSL** field (`8883/tcp`) should read `8883`. If the field is hidden, turn on
   **Show disabled ports**. If the port needs changing, enter `8883`, select
   **Save** in **Network**, and restart the app when prompted.
2. **Prepare the files.** Run `whiskerless setup` on the provisioning computer.
   Use the address the robot will use to reach Home Assistant. An existing setup
   can be rerun to get the listener file. Using the Home Assistant OS file
   shares (for example, through the Samba share app), copy the following files.

   | From the provisioning computer | To Home Assistant OS |
   | --- | --- |
   | `ca/ca.crt` | `/ssl/whiskerless/` |
   | `broker/server.crt` and `broker/server.key` | `/ssl/whiskerless/` |
   | `broker/haos/whiskerless.conf` | `/share/mosquitto/` |

   The source paths are under the directory printed by setup. Create the
   destination folders as needed. Keep the CA signing key on the provisioning
   computer. With externally issued certificates, use the broker certificate
   and key from the issuer for `server.crt` and `server.key`.
3. **Enable the file.** In **Mosquitto broker → Configuration → Options**,
   expand **Customize**. Turn on **active**. The **folder** field defaults to
   `mosquitto`. If it already names another folder, put `whiskerless.conf` in
   that folder under `/share/`. The file handles certificate authentication on
   the new listener. Leave **Require Client Certificate** at its existing setting.
4. **Start the listener.** Select **Save** in **Options** and choose **Restart**
   when prompted. If **Customize** was already active, restart the app from the
   **Info** tab to load the new file. In **Log**, check that Mosquitto opened
   port 8883. These steps use Mosquitto app version 7.1.3.

**Add another robot.** From the same provisioning computer, follow the pairing
instructions for the model being added (currently
[Litter-Robot 4](../../README.md#provision-the-robot)). Each robot gets its own
certificate from the same CA. Broker setup and restart are one-time steps.

**Check the connection before pairing (optional).** In Home Assistant's MQTT
integration, start listening to `whiskerless/setup-check`. On the provisioning
computer, publish a test message using the broker address from setup in place
of `mqtt.example.lan`. This example uses the default certificate paths.

```sh
mosquitto_pub -h mqtt.example.lan -p 8883 \
  -t whiskerless/setup-check -m connected \
  --cafile ~/whiskerless/ca/ca.crt --cert ~/whiskerless/client/client.crt \
  --key ~/whiskerless/client/client.key
```

Seeing `connected` in Home Assistant confirms that the broker accepted the
certificate and that Home Assistant received the message using its existing
login. With custom topic permissions, choose a topic both clients can use.

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
| Auth | TLS client certificate — Whisker's out of the box, yours after provisioning |

Three consequences:

- The broker must present a **server certificate the robot trusts** — that's the
  whole point of [certificates.md](certificates.md). Set that up first (or
  alongside this).
- The robot must be on a network that can **reach the broker's IP on port 8883**.
  Putting the robot and broker on the same IoT VLAN/subnet is the simplest setup.
- **The broker must listen on 8883.** The port is not provisionable and not
  configurable: it is a compile-time constant in the firmware, loaded at exactly one
  place, and 443 and 1883 appear nowhere in the image. Only the *host* is written
  during provisioning — and the CLI has no port of its own either, for the same
  reason: a whiskerless pointed at another listener would not be pointed at the
  robot.
- **The robot cannot log in with a username and password.** There is no field for
  one anywhere: not in the provisioning schema, not among the NVS keys the
  provisioning component persists, and not as a string in the firmware. It was built
  for AWS IoT, which authenticates clients by certificate, and
  provisioning writes the CA it should *trust* and the client certificate it
  presents. A listener that demands a password therefore locks the robot out, and
  no flag changes that. A listener demanding a *client certificate* is a different
  matter: out of the box the robot presents Whisker's factory certificate, which
  your CA did not sign and cannot validate, so it is refused — but provisioning
  replaces it with one your own CA signed, and then it is accepted. See
  [Requiring certificates](#requiring-certificates-instead-recommended).

  **So a listener for the robot either requires your certificate or allows
  anonymous clients.** Passwords are out either way.

  That is a limit on the *robot's* listener, not on your broker. Any login
  whiskerless or Home Assistant uses is a separate client on a separate,
  authenticated listener — see [below](#keeping-a-separate-authenticated-listener-for-home-assistant),
  which is the recommended shape for exactly this reason.

> **A broker you cannot configure is still a problem.** Whether you go anonymous
> or mutual-TLS, the robot's listener needs settings only its administrator can
> apply, and it must trust your CA. A managed or hosted broker you do not control
> is therefore out. Run your own Mosquitto for the robot — a second listener on
> the broker you already have, or a second instance on the same box.

**Ports are a convention, not a policy.** 1883 and 8883 are the registered ports for
plain MQTT and MQTT-over-TLS, and that is *all* they mean — neither one implies
anything about authentication. The split used here (authenticated on 1883, anonymous
on 8883) is a choice made in the config file below, not a property of the numbers, and
a broker is free to demand a password on 8883 and allow anonymous on 1883. What makes
the split work is `per_listener_settings true`: without it, `allow_anonymous` is a
single global setting, so adding the robot's listener to an authenticated broker either
locks the robot out or opens the whole broker.

## Minimal `mosquitto.conf`

This adds an **anonymous, TLS** listener on 8883 — the smaller step, and the one
to take if the broker is not yours to reconfigure twice. The robot still sends a
client certificate; the broker ignores it (`require_certificate false`), so
nothing has to match. Requiring it is one setting away and is
[recommended](#requiring-certificates-instead-recommended).

```conf
# Anonymous TLS listener for the Litter-Robot.
listener 8883
allow_anonymous true

# Your CA + server cert/key (see certificates.md).
cafile   /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile  /mosquitto/certs/server.key

# The robot presents a client certificate either way; this listener ignores it.
require_certificate false
```

The paths above are the official container's. On a broker installed from a package (Debian,
Ubuntu, Raspberry Pi OS), copy the three files into `/etc/mosquitto/certs/` and point the config
there, not at `~/whiskerless`. Ubuntu 26.04 confines mosquitto with an AppArmor profile that lets
it read only `/etc/mosquitto`, so a path into your home directory fails with "Unable to open".

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

## Requiring certificates instead (recommended)

Everything above assumes the robot has only its Whisker factory certificate,
which your CA did not sign and cannot validate — hence `allow_anonymous true`.
That is how a robot arrives, and it stays supported.

Since 0.2.0 whiskerless issues **every robot a certificate of its own** by
default, and a robot holding one still works on this anonymous listener, so there
is nothing to weigh. If your signing key lives elsewhere on purpose, `setup --auth
supplied` takes a certificate per robot from you instead and the result here is
the same. Only `--auth anonymous` leaves robots the certificate they shipped with,
and that is the one mode this section cannot be used with. Once every robot has been
re-provisioned, they all present something **your** CA signed and the listener can
demand it. `whiskerless robots` marks any that have not.

```conf
listener 8883
allow_anonymous false
cafile   /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile  /mosquitto/certs/server.key
require_certificate true
use_identity_as_username true
```

`use_identity_as_username` makes the certificate's common name the MQTT
username — and whiskerless names each robot's certificate after its serial, so
the broker log says `LR4C123456` rather than "anonymous".

**Order matters, and getting it wrong locks the robots out.** Provision every
robot first, confirm each one is talking, and only then flip the listener. A
robot still holding its factory certificate is refused by `require_certificate
true` with nothing on the robot to indicate why.

The CLI needs a certificate too, and gets one automatically — whiskerless issues
this machine an identity the first time it sets up or imports a CA, named
`whiskerless-<hostname>`.

**So does anything else on that listener.** A diagnostic subscriber, a bridge, a
recorder — whatever else was connecting anonymously to 8883 stops the moment you
flip this, and it fails as a dropped TLS connection with nothing in it to say
why. Issue each one an identity from the same CA first. Two separate things to get
right, and they are easy to confuse: the certificate's common name becomes the
MQTT **username** (that is what `use_identity_as_username` does), while the
**client id** is chosen by the client itself — and it is the client id that must
never be a robot's serial, because a duplicate one kicks that robot off its own
connection. Enumerate what is connected before you flip: `allow_anonymous true`
means the broker never had to tell you who any of them were.

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
