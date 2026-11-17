# #200 feat(ble): verify the WiFi join during provisioning — bad passwords fail loud, with the robot's own verdict

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:29-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#10](https://github.com/SisyphusMD/whiskerless/pull/10), opened by @CryingPecan on 2026-08-15, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

## The field incident that motivated this

Converting our second robot (LR4S1232338, ESP 1.4.4) to whiskerless today, provisioning reported success end-to-end — DEVICE_ID_SET, WiFi apply, cert write, APPLY_CONFIG, reboot, all clean. The robot then vanished: off the Whisker cloud (so the config *took*), never on WiFi, never on the broker. It looked exactly like the permanent-MQTT-death failure mode, and we spent half an hour on broker listeners, firewall rules, and stale UniFi client entries before finding the real cause: **one mistyped character in the WiFi password at the blind `getpass` prompt**. Re-provisioning with the right password had the robot on EMQX 30 seconds after reboot.

The provisioner can't see a bad password today — the WiFi finalize is a fixed 12 s `sleep` and nothing checks the outcome. But the robot knows, and will say so if asked.

## What this does

`prov-config` is stock esp-idf WiFi provisioning, and the stock protocol includes `CmdGetStatus`, which the codec never sent. After SetConfig+Apply, we now poll it (1.5 s cadence, 20 s ceiling) instead of sleeping blind:

- **Connected** → prints `WiFi connected (ip=192.168.2.41)` and proceeds early (a beat of settle first — got-IP is what finalizes the provisioning state machine, and the old 12 s was really standing in for that). You also get the robot's fresh IP for free, which is exactly what you want next anyway.
- **ConnectionFailed / AuthError** → raises `WiFi join failed: authentication failed — almost always a mistyped WiFi password`, **before the endpoint/cert writes**, so the broker config is untouched and the remedy is just re-running provision.
- **ConnectionFailed / NetworkNotFound** → same, naming the SSID.
- **No answer** (firmware without GetStatus, GATT hiccups) → degrades to the old behavior: run out the window, warn `verify the robot actually appears on your network`, continue. A silent firmware can't fail a good join.

## Wire model (the two proto3 gotchas)

- `fail_reason` `AuthError` is enum value **0**, but it's a oneof arm, so protobuf-c emits the field anyway — presence is explicit. The tests pin this exact encoding (`0x50 0x00`).
- `sta_state` `Connected` is **also** 0 — a plain field, so proto3 keeps it *off* the wire, making a bare `RespGetStatus` ambiguous. Success is therefore only ever read from the `WifiConnectedState` oneof arm (which esp-idf always populates, with `ip4_addr`), never inferred from an absent `sta_state`.

## Caveat, flagged like last time

The builders/parsers match the stock esp-idf `wifi_config.proto` byte-for-byte and are fully unit-tested (13 new tests: wire fixtures both directions, plus the verify loop against a fake transport — auth failure raises, connected returns, silent firmware falls through). But **the GetStatus round-trip has not yet been exercised against a live robot** — both of ours are now provisioned and happy, and I didn't re-provision one just to watch it succeed. It's a read-only query, so the safe live check is: pairing mode → connect → GetStatus, no writes. First re-provision by whoever gets there first; happy to run it on our hardware next time either robot needs a BLE touch.

Note: `tests/test_link.py` / `tests/test_mqtt.py` have 15 failures on current `main` in my local py3.12 env, pre-existing and untouched by this branch (565 → 578 passing).

## cody, 2026-11-17T08:59:29-08:00

_@SisyphusMD on GitHub, 2026-08-16:_

Merged as 7506ef0, with you as the author.

Two notes on what changed on the way in. I rebased it onto main and added a one-line type annotation on the `fail_reason` lookup so it clears the strict mypy gate; worth knowing that `AUTH_ERROR` is enum value 0, so a truthiness check there would have silently swallowed the mistyped-password case this whole path exists to name. The commit message is the single-line house style, and the wire notes you wrote are preserved in the docstrings where they get read.

Also worth flagging: main's history was rewritten today, so every commit before this one has a new SHA. You will want to reset your fork against the new main rather than merging into it.

Closing this since the commit is in. Thanks for this one, the failure it catches had been getting diagnosed as a dead unit.

## cody, 2026-11-17T08:59:29-08:00

_@SisyphusMD on GitHub, 2026-08-16:_

Reopened briefly to push the rebased branch, since maintainer write access to a fork only exists while the PR is open. This branch now matches main, so it is a clean base to work from. Re-closing; the commit is in as 7506ef0.
