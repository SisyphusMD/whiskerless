# LR4 BLE provisioning — protobuf schemas

These two `.proto` files are the **byte-verified** Protocol Buffers schemas for the
Litter-Robot 4's BLE re-provisioning GATT endpoints, reconstructed from the ESP
firmware image — every field number, wire-type, and enum value was decoded from
the firmware's `protobuf-c` descriptor tables (nothing guessed):

- **`whisker_config.proto`** — the `whisker-config` endpoint: get/set the device
  serial, reboot.
- **`whisker_mqtt_config.proto`** — the `mqtt-config` endpoint: write the CA cert
  (chunked), set the broker host/endpoints, apply. This is the core un-clouding
  step — provision *your* CA as `CERT_AWS_ROOT_CERT` so the robot trusts your
  local broker.

They are **reference**. The runtime provisioning code is a hand-written, pure-Python
protobuf codec under `src/whiskerless/ble/` (no `protoc`/codegen step) — it sends
the specific frames provisioning needs. These schemas document the *full* protocol,
including messages the codec doesn't currently use, for anyone extending it.
