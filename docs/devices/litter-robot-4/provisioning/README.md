# LR4 BLE provisioning — protobuf schemas

These two `.proto` files are the **byte-verified** Protocol Buffers schemas for the
Litter-Robot 4's BLE re-provisioning GATT endpoints, reconstructed from the ESP
firmware image — every field number, wire-type, and enum value was decoded from
the firmware's `protobuf-c` descriptor tables (nothing guessed):

- **`whisker_config.proto`** — the `whisker-config` endpoint: set the device id
  (the client id, written as the serial), read it back, reboot. What a *factory*
  robot returns from that read is unresolved — the runtime code formats the
  6-byte response as a MAC, while a descriptor comment suggests the serial
  string; see the backlog's #52.
- **`whisker_mqtt_config.proto`** — the `mqtt-config` endpoint: write the CA cert
  (chunked), set the broker host/endpoints, apply. This is the core un-clouding
  step — provision *your* CA as `CERT_AWS_ROOT_CERT` so the robot trusts your
  local broker.

They are **reference**. The runtime provisioning code is a hand-written, pure-Python
protobuf codec under `src/whiskerless/ble/` (no `protoc`/codegen step) — it sends
the specific frames provisioning needs. These schemas document the *full* protocol,
including messages the codec doesn't currently use, for anyone extending it.

## Provenance notes

The firmware images these schemas were decoded from are public and still mirrored at
[huntergregal/litterrobot_firmware](https://github.com/huntergregal/litterrobot_firmware)
under `litterrobot4/ESP/` — `ESP_1_1_65_OTA.bin` is the one the field numbers came from.

**The Whisker-app BLE capture has now been decoded** — see
[app-onboarding-capture.md](app-onboarding-capture.md) for the complete field-level
record of what the official app writes, in order, with sizes and timings. That
document exists so this capture never has to be repeated; the raw `.pklg` is
deliberately not in the repo, because protocomm's `no_sec, no_pop` means it carries
the WiFi passphrase, the serial and the device private key in cleartext.

**The earlier (2025) capture was not retained.** `ble/messages.py` and
[reverse-engineering.md](../../../reverse-engineering.md) both cite a captured app session,
and it is what revealed that the app runs the Wi-Fi *finalize* as part of onboarding — the
step whose absence wedged the first re-provisioning attempts. The capture file itself was
never committed and no copy survives, so those two references are the whole record. Both
describe only the `prov-config` Wi-Fi frames; **neither establishes anything about what the
app does with `mqtt-config`** — the question the 2026-08-16 capture went on to answer
in [app-onboarding-capture.md](app-onboarding-capture.md). If that
capture is ever redone, commit the decoded transcript here.
