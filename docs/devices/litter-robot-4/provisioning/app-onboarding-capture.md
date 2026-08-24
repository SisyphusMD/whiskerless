# The Whisker app's BLE onboarding, decoded

A complete, field-level record of what the official Whisker iOS app does to a
Litter-Robot 4 over BLE, captured 2026-08-16 and decoded frame by frame. It exists
so nobody has to capture this again: every value the app writes, in order, with
sizes and timings.

**Provenance.** iOS sysdiagnose with Apple's Bluetooth logging profile installed,
taken immediately after a re-onboarding of a robot that was already provisioned to
a local broker. Decoded from `logs/Bluetooth/bluetoothd-hci-*.pklg` — HCI → ACL →
L2CAP → ATT → protocomm protobuf, against the schemas in
[`whisker_config.proto`](whisker_config.proto) and
[`whisker_mqtt_config.proto`](whisker_mqtt_config.proto). Robot ESP firmware 1.1.75.

**The raw capture is not in this repo and must not be.** Because protocomm runs
`no_sec, no_pop`, it carries the WiFi passphrase, the robot serial, and the device
private key in cleartext. Everything below is redacted: secrets are described by
length and kind, never reproduced.

## What this settles

- **The app rewrites the device identity on every onboarding**, including on a robot
  that already had a valid one. It writes all three certificate slots — root CA,
  device certificate, device private key. This is what makes overwriting the factory
  identity *recoverable without opening the robot*: re-onboarding in the app issues a
  fresh identity. See the backlog's #70.
- **The robot is never identified by serial over BLE.** It advertises one service
  UUID and nothing else; its own device-id read returns a **MAC**. The serial comes
  from the QR code and is *written into* the robot. That is why backlog #52
  (auto-filling `--serial` from the device id) was never viable.
- **The WiFi network list the user picks from comes from the robot**, not the phone —
  `prov-scan` makes the robot scan and report what it can see.

## Layer 1 — discovery and connection

The advertisement carries three AD structures and no identifying information:

| AD type | value |
|---|---|
| `0x01` Flags | `0x06` — LE General Discoverable, BR/EDR not supported |
| `0x0A` TX Power | `9` dBm |
| `0x07` Complete 128-bit Service UUIDs | `b7ee1c20-dcfd-4208-8813-14845cac5212` |
| `0x12` Slave Conn Interval Range | `0x0006`–`0x0010` |

No local name, no manufacturer data, no serial. **The app scans for that service UUID
and connects to whatever answers.** Since a robot only advertises while it is in
pairing mode, which a three-second hold on Connect puts it into, exactly one is ever
discoverable, so there is nothing to disambiguate and no device list to present.

The GAP device name, read after connecting, is `LitterRobot4` on every unit.

Connection observed at `14:24:19.087`. The robot's BLE address is the base MAC **+2**
(device id reported `…:1d:34`, BLE address `…:1d:36`).

**MTU: the app requests 527, the robot grants 500.**

## Layer 2 — the GATT map

One primary service, `b7ee1c20-dcfd-4208-8813-14845cac5212`, spanning handles
`0x0028`–`0xFFFF`, with six characteristics — all `props=0x0A` (read + write), each
followed by a `0x2901` Characteristic User Description holding the endpoint name:

| value handle | characteristic UUID | endpoint |
|---|---|---|
| `0x002a` | `b7ee0001-dcfd-4208-8813-14845cac5212` | *(not exercised in this capture)* |
| `0x002d` | `b7ee0002-…` | **prov-config** |
| `0x0030` | `b7ee0003-…` | *(not exercised)* |
| `0x0033` | `b7ee0004-…` | **prov-scan** |
| `0x0036` | `b7ee0005-…` | **mqtt-config** |
| `0x0039` | `b7ee0006-…` | **whisker-config** |

The app discovers the `0x2901` descriptors but **never reads them** — it maps
endpoints by characteristic UUID. whiskerless reads them instead, which is why the
endpoint-name strings appear nowhere in this capture.

Every exchange is **write-then-read on the same handle**: the request goes as an ATT
Write Request, and the response is fetched with a Read Request on that same
characteristic. There are no notifications.

## Layer 3 — the full sequence

Times are wall clock from the capture; the whole thing takes **72 seconds**, of which
about 30 is the user picking a network and typing a password.

```
14:24:19.517  ATT   MTU exchange                    527 requested -> 500 granted
14:24:19.657  ATT   service + characteristic discovery
14:24:21.435  GATT  read device name                "LitterRobot4"
14:24:23.804  whisker-config  DEVICE_ID_REQUEST
14:24:24.236  whisker-config  DEVICE_ID_RESPONSE    6-byte MAC (NOT the serial)
14:24:24.238  prov-scan       cmd_scan_start        blocking=1 passive=0 group=5 period=120ms
14:24:28.475  prov-scan       resp_scan_start
14:24:28.477  prov-scan       cmd_scan_status
14:24:28.835  prov-scan       resp_scan_status      finished=1, 22 results
14:24:28.838  prov-scan       cmd_scan_result       start=0  count=4
14:24:28.997  prov-scan       resp_scan_result      4 entries
   ... repeated for start=4, 8, 12, 16, 20 — 22 networks in pages of four
              << user picks the network and types the passphrase >>
14:24:59.715  whisker-config  DEVICE_ID_SET         "LR4C……" (10 chars, from the QR)
14:25:00.195  whisker-config  DEVICE_ID_SET_RESPONSE  Success
14:25:00.197  prov-config     cmd_set_config        ssid + passphrase (cleartext)
14:25:00.716  prov-config     resp_set_config
14:25:00.720  prov-config     cmd_apply_config
14:25:01.315  prov-config     resp_apply_config
              << ~10 s while the robot associates >>
14:25:11.320  prov-config     cmd_get_status
14:25:11.596  prov-config     resp_get_status       connected, ssid, bssid, ch 1, ip 0.0.0.0
14:25:11.599  mqtt-config     ENDPOINT_WRITE  HOST             a2wz9c6y6mikoy-ats.iot.us-east-1.amazonaws.com
14:25:11.997  mqtt-config     ENDPOINT_WRITE  CLOUD_ENDPOINT   prod/LR4/<serial>/command
14:25:12.437  mqtt-config     ENDPOINT_WRITE  DEVICE_ENDPOINT  prod/LR4/<serial>/activity
14:25:12.878  mqtt-config     CERT_WRITE      CERT_AWS_ROOT_CERT   1188 B, 12 chunks
14:25:18.558  mqtt-config     CERT_WRITE      CERT_DEVICE_CERT     1484 B, 15 chunks
14:25:24.718  mqtt-config     CERT_WRITE      CERT_DEVICE_KEY      1702 B, 18 chunks
14:25:31.601  mqtt-config     APPLY_CONFIG
14:25:31.958  whisker-config  DEVICE_REBOOT
```

### The last page must ask only for what remains

This capture does not show the final `cmd_scan_result`'s `count`, and copying the
pattern without thinking about the boundary produced a real failure: whiskerless
asked for a full four every time, so a robot reporting 30 networks served 0-27 and
then sent a request for 28-31. The firmware answers that out-of-range read by
**dropping the BLE link** — not a short page, not an error — in the middle of
provisioning, after the operator had done everything right. Any result count that is not
a multiple of four ends there, which is most households, and it presents as flaky
Bluetooth. Proven live 2026-08-18 on a robot seeing 30 networks; fixed by clamping
to `min(page, count - start)`.

### `resp_get_status` reports the join before DHCP

At `14:25:11.596` the robot reports itself connected — with `ip4_addr = "0.0.0.0"`.
That is the pre-DHCP window: a `CONNECTED` status does not imply a lease.

The address often arrives a second or two later, so reading the status once at the
moment of association finds `0.0.0.0` and throws away a lease that was seconds off;
whiskerless keeps polling briefly after association instead.

**But the address is not dependable, and `0.0.0.0` is not the only way it fails.**
Both robots leased inside the extra window on 2026-08-18, which is what the earlier
claim of "proven" rested on. On 2026-08-19 neither did: one answered `1.0.0.0` while
its real lease was a `192.168` address, and the other never reported one at all.
`1.0.0.0` is what `esp_ip4addr_ntoa()` prints for the integer `1`, so the likeliest
reading is a firmware field holding something that is not an address — and nothing
on this side can parse an address out of a value the robot never sent.

So the address is reported only when it is plausibly a LAN lease, and its absence is
not mentioned at all: the join is what that step verifies, and it is confirmed either
way. Do not restore a bare "is it `0.0.0.0`" guard — that is exactly what let
`1.0.0.0` end the wait early and print an address the robot did not have.

### The certificate writes

All three slots, in this fixed order, chunked at a flat **100 bytes** regardless of
the 500-byte MTU:

| slot | `CertificateType` | total | chunks | wall time |
|---|---|---|---|---|
| AWS root CA | `1` | 1188 B | 12 | 5.7 s |
| device certificate | `2` | 1484 B | 15 | 6.2 s |
| device private key | `3` | 1702 B | 18 | 6.6 s |

Each chunk is one `MqttCertificateWriteRequest` carrying `type`, `key` (the chunk
text), `total_size`, `offset`, `size`, answered by an empty
`MqttCertificateWriteResponse` with `status` absent, i.e. `Success`. Offsets advance
strictly by 100 with a short final chunk (88, 84 and 2 bytes respectively).

The private key is a `-----BEGIN RSA PRIVATE KEY-----` PEM. The device certificate
and the root CA are `-----BEGIN CERTIFICATE-----` PEMs.

**All 46 chunks are staged before the single `APPLY_CONFIG`.** That is consistent
with the firmware committing on apply rather than on receipt, though the app
behaving this way is not proof the firmware requires it.

### `prov-scan` result entries

`resp_scan_result` returns up to four `WiFiScanResult` entries per request:

| field | meaning |
|---|---|
| 1 | SSID |
| 2 | channel |
| 3 | RSSI, an int32 sign-extended into a varint (so it decodes as a huge unsigned value; `2^64 − 51` is −51 dBm) |
| 4 | BSSID, 6 raw bytes |
| 5 | auth mode (`3` = WPA2-PSK across almost every entry here, `4` and `7` also seen) |

A naive protobuf pretty-printer will occasionally mis-render field 4 as a nested
message, because six arbitrary bytes sometimes parse as valid tag/length pairs.
Treat it as opaque bytes.

## How whiskerless differs

Our sequence — `DEVICE_ID_SET → WiFi SetConfig+Apply → wait → endpoints → CA →
APPLY → reboot` — matches the app's ordering for every step we perform. The
differences are:

| | Whisker app | whiskerless |
|---|---|---|
| endpoint mapping | by characteristic UUID | reads the `0x2901` descriptors |
| WiFi network choice | `prov-scan`, robot-side scan, list in the UI | user types the SSID |
| cert chunk size | flat 100 B | `MTU − 40` (460 at MTU 500) |
| device cert / key | **written every onboarding** | never touched, by design |
| join confirmation | `get_status` after apply | same |

Two follow-ups fall out of this, both tracked in the backlog: offering a network
list via `prov-scan` instead of asking the user to type an SSID, and whether to
align the chunk size with the app's conservative 100 bytes.
