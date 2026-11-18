# #222 Prove unattended robot provisioning in CI

- Kind: issue, state: open, by cody, created 2026-11-17T15:28:07-08:00
- Labels: status:ready, type:spike; milestone: none

Give whiskerless a repeatable Forgejo test that runs the real Bluetooth provisioning flow on a designated LR4 without anyone at the robot. This would help verify shared setup changes such as #217.

- **Verify remote pairing.** Determine whether the stock LR4 honors a Connect hold over MQTT. Confirm success by detecting its BLE provisioning advertisement.
- **Run real provisioning.** Use a manually dispatched Forgejo job to run one test at a time through an active ESPHome Bluetooth proxy. Require provisioning acknowledgments and fresh MQTT telemetry from the test robot.
- **Prove recovery.** Simulate a failure after pairing clears Wi-Fi. Verify that a known-good build restores connectivity remotely and that CI reports the candidate as failed.

**Done when** CI demonstrates successful provisioning and recovery from a failed run without anyone physically at the robot.
