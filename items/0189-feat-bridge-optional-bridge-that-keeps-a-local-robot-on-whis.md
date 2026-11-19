# #189 feat(bridge): optional bridge that keeps a local robot on Whisker's cloud

- Kind: pull, state: closed, by cody, created 2026-11-17T08:45:09-08:00
- Labels: none; milestone: none
- refs/pull/189/head -> main, merged: False

Refs #186.

Moved from https://github.com/SisyphusMD/whiskerless/pull/15, opened by Stephan Garland (@stephanGarland on GitHub) on 2026-11-06, with his commits unchanged. **Not yet reviewed.** Sent as an AGit pull request so CI does not run unreviewed code; a maintainer re-opens it from a branch after review.

---

I split this work into three separate PRs as I wasn't sure if you'd want the bridge and broker.

## What and why

Taking a robot off Whisker's cloud also takes away the Whisker app. With this bridge you can keep both. The robot stays on your local broker, and the bridge connects to Whisker's AWS IoT endpoint as the robot, relaying messages unchanged in both directions. The app keeps working, and every command the cloud sends is visible locally, which makes working out new commands much easier. It's inspired by [rethink](https://github.com/anszom/rethink)'s bridge mode; no rethink code is used.

- **Library:** `whiskerless.bridge` works with any model; the local and cloud topic prefixes are configurable.
- **Home Assistant:** a Cloud bridge entry with an on/off switch, a connection sensor, a traffic event (so messages show up in the logbook) and a send-message action. There's an example dashboard in `examples/cloud-bridge/`.
- **Getting the robot's identity:** the Whisker app writes the robot's certificate and key over BLE during setup. `docs/setup/cloud-bridge.md` explains how to capture that on iOS or Android, and `scripts/cloud_identity.py` pulls the certificate and key out of the capture.
- Messages you send toward the robot go through `safety.py`; traffic relayed from the cloud passes through untouched.

Tested on a real EVO: with the bridge running, the app stayed fully usable and every app action showed up on the local broker.

Possible follow-up: the app gets that certificate and key from Whisker's API. If whiskerless could fetch it with the user's login, the BLE capture wouldn't be needed.

## Sibling repo

- [ ] Ported to the sibling repo (link the PR)
- [x] Not applicable, because: it relays to Whisker's cloud specifically.
- [ ] Deliberate variance, recorded in `VARIANCE.md`

## Checks

- [x] Regression test that fails on the parent commit
- [x] `STANDARD.lock` still in sync (no vendored file edited in place)

The library suite passes at 99.19% and the integration suite at 99.78%, with `safety.py` and `config_flow.py` at 100%.

## cody, 2026-11-17T23:05:29-08:00

Thanks for building this and testing it on your EVO, @stephanGarland. I’m closing this because a live cloud bridge is outside the scope of whiskerless. Keeping the app working would mean maintaining the cloud connection and handling commands it sends to the robot.

Which feature of the Whisker app were you trying to keep by building the bridge? I’d like to see if whiskerless can provide it locally.
