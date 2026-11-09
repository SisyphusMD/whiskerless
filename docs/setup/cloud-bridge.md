# Cloud bridge

A robot whiskerless has provisioned talks only to your broker, so the Whisker app
loses it. The cloud bridge brings the app back without giving up local control: it
connects to Whisker's cloud *as the robot*, using the robot's own cloud identity, and
relays the robot's MQTT both ways, unchanged.

```
Whisker app ⇄ Whisker cloud (AWS IoT) ⇄ bridge (Home Assistant) ⇄ your broker ⇄ robot
```

Because every message passes through your broker in plaintext, the bridge is also
the way to read exactly what the cloud sends the robot: change a setting in the app
and watch the command arrive. Bridge mode is inspired by
[rethink](https://github.com/anszom/rethink)'s bridge mode for LG appliances.

The bridge is optional. Local control works without it; it is for keeping the app,
or for studying the protocol.

## How it relays

| From | Topic | To |
|---|---|---|
| cloud | `<cloud prefix>/<serial>/command` | your broker, `<local prefix>/<serial>/command` |
| robot | `<local prefix>/<serial>/activity`, `/event`, `/state` | cloud, the same leaf under `<cloud prefix>/<serial>` |

The prefixes are what each side was provisioned with:

| Robot | Local prefix (whiskerless) | Cloud prefix (Whisker app) |
|---|---|---|
| Litter-Robot 4 | `prod/LR4` | `prod/LR4` |
| Litter-Robot EVO | `prod/LR4` | `prod/robots` |

The bridge does not read what it relays, so it works for any robot whiskerless can
provision.

**One connection per robot.** AWS IoT allows one connection per client ID, and the
client ID is the robot's serial. If the robot is still connected to the cloud when
the bridge connects, the two keep disconnecting each other. Always re-provision the
robot onto your broker *before* switching the bridge on.

## What you need

- The robot provisioned onto your broker, with Home Assistant's MQTT integration
  connected to the same broker ([MQTT broker](mqtt-broker.md), [Home Assistant](home-assistant.md)).
- Home Assistant able to reach the Internet on TCP 8883.
- The robot's cloud identity: Amazon's root CA, the robot's device certificate and
  its private key. The Whisker app writes these to the robot over Bluetooth during
  onboarding, unencrypted, so a Bluetooth capture of an onboarding contains them.
  The steps below take that capture, extract the identity, and put the robot back
  on your broker.

## 1. Capture the app's Bluetooth onboarding

You onboard the robot with the Whisker app as if setting it up new, while your phone
records its Bluetooth traffic.

> **The capture is a secret.** It contains your Wi-Fi passphrase and the robot's
> private key in cleartext. Keep it off shared drives, and delete it once the
> identity is extracted.

### iPhone

1. On the iPhone, open
   [developer.apple.com → Bug Reporting → Profiles and Logs](https://developer.apple.com/bug-reporting/profiles-and-logs/),
   sign in with any Apple ID, and download the **Bluetooth** profile for iOS.
2. Install it: **Settings → General → VPN & Device Management**, tap the downloaded
   profile, and install. Restart the phone if the profile says to.
3. Put the robot in pairing mode (see its manual; the Connect button), and run the
   Whisker app's onboarding for it: **Add a Device**, or the robot's Wi-Fi
   reconnect option. Pick your network and let it finish.
4. Straight away, trigger a sysdiagnose: press and hold **both volume buttons and
   the side button** together for about one second, until the phone vibrates
   briefly.
5. Wait about ten minutes while it builds.
6. Open **Settings → Privacy & Security → Analytics & Improvements → Analytics Data**,
   find the newest `sysdiagnose_….tar.gz`, tap it, and share it to your computer
   (AirDrop works).
7. On the computer, extract only the Bluetooth log:

   ```bash
   tar -xzf sysdiagnose_*.tar.gz --wildcards '*/logs/Bluetooth/bluetoothd-hci-latest.pklg'
   ```

   (On macOS's `tar`, drop `--wildcards`.) The file you want is
   `logs/Bluetooth/bluetoothd-hci-latest.pklg`. Delete the sysdiagnose afterwards; it
   holds much more than Bluetooth.

**Alternative: a live capture.** With the profile installed and the iPhone connected
to a Mac by USB, Apple's **PacketLogger** (in Xcode's *Additional Tools*) can record
the phone's Bluetooth live: **File → New iOS Trace**, run the onboarding, then save
the trace as `.pklg`.

### Android

1. Turn on **Developer options**: **Settings → About phone**, tap **Build number**
   seven times.
2. In **Settings → System → Developer options**, turn on **Enable Bluetooth HCI snoop
   log**. Where the menu offers a mode, choose **Enabled** (full), not *Filtered*.
3. Turn Bluetooth off and on again, so the log starts.
4. Put the robot in pairing mode and run the Whisker app's onboarding for it, as
   above.
5. Retrieve the log. Where it lands differs by vendor and Android version:
   - With `adb` (USB debugging on): `adb bugreport bugreport.zip`, then look inside
     the zip for `btsnoop_hci.log`, usually under `FS/data/misc/bluetooth/logs/` or
     `FS/data/log/bt/`.
   - Some phones store it where you can copy it directly, such as
     `/sdcard/btsnoop_hci.log` or `/sdcard/Android/data/btsnoop_hci.log`; the
     Developer options entry may show the path.
6. Turn the snoop log off again, and delete the bug report once the log is out.

## 2. Extract the identity

From a clone of this repository:

```bash
python scripts/cloud_identity.py bluetoothd-hci-latest.pklg cloud_identity
# or: python scripts/cloud_identity.py btsnoop_hci.log cloud_identity
```

It reads either format and writes `root_ca.pem`, `device.crt` and `device.key`
(mode 0600) and a `summary.json` with the host, topics and serial. It prints the
host, the topics, the serial and each file's size, never the key. A missing file
means the capture did not cover the whole onboarding; capture again.

Then **delete the capture.**

## 3. Put the robot back on your broker

The app's onboarding pointed the robot at the cloud. Re-provision it onto your
broker as usual (`whiskerless provision`), with the robot in pairing mode — it does
not reliably advertise while connected. Provisioning gives the robot an identity
from your CA; the captured cloud identity stays with the bridge.

## 4. Add the bridge in Home Assistant

1. Copy the three identity files into your Home Assistant config folder, by default
   `whiskerless/cloud_identity/` (for example `/config/whiskerless/cloud_identity/`
   on Home Assistant OS, over SSH or Samba). Keep them readable only by Home Assistant.
2. **Settings → Devices & services → Add integration → Whiskerless → Cloud bridge.**
   Enter the robot's serial, and check the topic prefixes against the table above:
   for a Litter-Robot EVO onboarded by the app, the cloud prefix is `prod/robots`.
   The cloud host is filled in, and matches `summary.json`'s `host`.
3. Turn on **Cloud bridge** on the new device. **Cloud bridge state** goes to
   *Connected*, and the Whisker app shows the robot online.

The switch remembers its position across restarts, and the bridge reconnects on its
own, backing off from 5 seconds to 5 minutes, while the state reads *Error* with the
reason.

## Watching and sending

- **Cloud bridge traffic** fires once per relayed message, with its direction, topic
  and payload (cut at 2048 characters), so the logbook lists the traffic in order.
- **`whiskerless.send_bridge_message`** sends a message by hand: toward the robot
  (its command topic) or toward the cloud as the robot (its activity topic), with an
  optional other last topic level. Commands toward the robot pass the
  [safety guard](../../README.md#safety-first) when it can read them; one it cannot
  classify needs **Allow untraced commands**, and brick-class commands are refused
  regardless. The cloud's own commands are relayed as they are: they are the vendor's.
- [`examples/cloud-bridge`](../../examples/cloud-bridge/README.md) has a dashboard
  with the toggle, the last message, the traffic log and a send form.

For protocol work, the `scripts/` folder has the rest of the kit:
`cloud_poll.py` logs the cloud's named view of the robot (`catDetect`,
`displayCode`, …) as it changes, and `timeline.py` merges it with an MQTT capture
(`mosquitto_sub -t 'prod/#' -F '%J'`) so each raw value sits next to its name.
`ble_scan.py`, `ble_gatt.py` and `ble_protover.py` survey a robot's Bluetooth
provisioning service without changing anything.

## Turning it off, and going back to the cloud

Turn off **Cloud bridge** to stop relaying; the robot stays on your broker. To put the
robot back on the cloud for good, delete the bridge entry and re-onboard the robot in
the Whisker app ([Recovery](../recovery.md)). The app issues a new identity on every
onboarding, so the bridge's copy may stop working after one; capture again if you
want the bridge back.

## Keeping the identity safe

Whoever holds the three files can connect to Whisker's cloud as your robot. Treat
them like a password: mode 0600, out of shared backups, and nowhere public. The
bridge's diagnostics download leaves out the serial and every payload, since cloud
messages can carry your pets' profiles.
