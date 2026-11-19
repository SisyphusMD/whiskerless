# #229 Generate Home Assistant OS Mosquitto configuration in whiskerless setup

- Kind: issue, state: closed, by cody, created 2026-11-18T07:07:19-08:00
- Labels: status:in-progress, type:feature; milestone: none

## What

Have `whiskerless setup` generate the listener configuration for the official Home Assistant OS Mosquitto broker app and show where to copy it and the three broker certificate files. Document the setup in the same PR. This came up while reviewing #190.

## Why

The current guide asks the person setting up the broker to translate a generic Mosquitto example into Home Assistant settings. The broker only needs to recognize a client certificate signed by the configured CA. The listener can be set up once for any supported robot that uses that authentication method.

## Done when

- [ ] The generated configuration uses the broker certificate, its private key and the trusted CA certificate. It requires a trusted client certificate. Generating it needs no robot model or serial number.
- [ ] The guide gives the file destinations and walks through the Mosquitto app using its English screen labels, including **Configuration → Options → Customize**, the **active** switch, the **folder** field, **Save** and **Restart**. It explains how to tell whether port 8883 already has a listener before applying the example.
- [ ] The guide shows how to confirm the generated listener accepts a trusted client without an MQTT password and that Home Assistant can still use its existing login. Cover the generated configuration in tests.
- [ ] “Add another robot” points to the supported model’s pairing instructions. A second robot provisioned with the same CA needs no broker edit, file copy or restart.
