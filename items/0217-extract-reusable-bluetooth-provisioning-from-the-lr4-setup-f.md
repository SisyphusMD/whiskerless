# #217 Extract reusable Bluetooth provisioning from the LR4 setup flow

- Kind: issue, state: open, by cody, created 2026-11-17T14:53:00-08:00
- Labels: status:in-progress, type:chore; milestone: none

Whiskerless’s Bluetooth setup code currently assumes every robot is an LR4. PR #188 adds EVO support by broadening the existing scanner and provisioning checks to accept either model. Extract the setup sequence both models can use so that each model can keep its own discovery and identity checks.

- Keep the existing LR4 entry point, device selection, serial validation, and MQTT defaults.
- Add regression tests for LR4 discovery and provisioning, including selection by explicit Bluetooth address.
- Verify on a real LR4 that setup still works and the robot connects to the configured broker.

This is the prerequisite for #188. The EVO-specific changes stay in #188.

## cody, 2026-11-19T16:33:56-08:00

Decision: Split Bluetooth setup by layer and keep it modular and DRY. ble/ keeps the one reusable setup sequence (Wi-Fi, certificates, MQTT broker) and never names a robot model. Each model supplies a provisioning profile (BLE service UUID and advertiser name, serial validation, default MQTT topics); the LR4 profile lives in devices/litter_robot_4/. The existing LR4 entry point and explicit-address selection keep working, and the LR4 provisioning service is still required before the first write. Splitting cli.py is separate work. Why: Model-specific checks inside ble/provision.py would grow one branch per robot (PR #188 adds serial-prefix checks there); a profile per model keeps EVO and later robots in their own folders.

Decided by: Cody, 2026-11-19.

## cody, 2026-11-19T16:33:57-08:00

Claude (Cody's session) has this issue.

## cody, 2026-11-19T17:19:34-08:00

Status: PR #235 is open with every check green, including the AI review, which found nothing blocking. One suggestion was answered on the PR. The real-LR4 check is still to do. It cannot run remotely yet, because pairing mode needs Connect held at the robot and pairing wipes its Wi-Fi. Remote pairing over MQTT and the Bluetooth proxy path are unproven (#222). #235 waits for Cody to be home to run whiskerless provision from the branch and confirm the robot reaches the broker. Then merge.

## cody, 2026-11-19T21:14:13-08:00

Status: unchanged since comment 38980. PR #235 is green and mergeable, branch chore/217-ble-provisioning-profile in worktree ~/repos/SisyphusMD/whiskerless-217. It waits only on the real-LR4 check: run `whiskerless provision` from the branch while Cody holds Connect, confirm the robot reaches the broker, then merge #235. No crons or holds. The session is rotating; the successor picks this up.

## cody, 2026-11-20T00:41:55-08:00

Status: PR #235 is unchanged, and still waits only on the LR4 bench test with Cody home (run `whiskerless provision` from the branch while he holds Connect, then confirm the robot reaches the broker). #218 and #219 have merged, so this is the last prerequisite for #188. The session is rotating; no crons or holds are running.
