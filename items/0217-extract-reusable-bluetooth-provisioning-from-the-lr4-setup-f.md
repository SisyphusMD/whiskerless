# #217 Extract reusable Bluetooth provisioning from the LR4 setup flow

- Kind: issue, state: open, by cody, created 2026-11-17T14:53:00-08:00
- Labels: status:ready, type:chore; milestone: none

Whiskerless’s Bluetooth setup code currently assumes every robot is an LR4. PR #188 adds EVO support by broadening the existing scanner and provisioning checks to accept either model. Extract the setup sequence both models can use so that each model can keep its own discovery and identity checks.

- Keep the existing LR4 entry point, device selection, serial validation, and MQTT defaults.
- Add regression tests for LR4 discovery and provisioning, including selection by explicit Bluetooth address.
- Verify on a real LR4 that setup still works and the robot connects to the configured broker.

This is the prerequisite for #188. The EVO-specific changes stay in #188.
