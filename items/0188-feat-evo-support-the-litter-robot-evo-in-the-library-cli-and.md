# #188 feat(evo): support the Litter-Robot EVO in the library, CLI and integration

- Kind: pull, state: open, by cody, created 2026-11-17T08:45:08-08:00
- Labels: none; milestone: none
- refs/pull/188/head -> main, merged: False

Refs #185.

Moved from https://github.com/SisyphusMD/whiskerless/pull/14, opened by Stephan Garland (@stephanGarland on GitHub) on 2026-11-06, with his commits unchanged. **Not yet reviewed.** Sent as an AGit pull request so CI does not run unreviewed code; a maintainer re-opens it from a branch after review.

---

I split this work into three separate PRs as I wasn't sure if you'd want the bridge and broker.

## What and why

The EVO provisions over the same BLE protocomm channel as the LR4 and uses the same MQTT envelope, but its register map is banked and different, so the LR4 driver can't talk to it. This PR adds it in two commits, which can be reviewed (or merged) separately: the library first, then the integration.

**Library** (`devices/litter_robot_evo/`, laid out like `litter_robot_4`)
- **Provisioning:** BLE now accepts the EVO's service UUID, name and `LRE-…` serial (on the EVO the long hyphenated label line is the serial). EVOs get their native `prod/robots/<serial>/…` topics; LR4 provisioning is unchanged.
- **Protocol:** commands are `0xTTBBRRVVVV` (read or write, bank, register, value). A single message can read every readable register, and the robot answers in one reply.
- **Commands:** separate screen and status-LED brightness, cycle delay, lockout, sleep schedule, the robot's clock, clean and empty cycles, change filter, drawer-level reset, power on/off. EVO commands are classified separately in `safety.py`, so LR4 behavior doesn't change.
- **Also:** a `whiskerless evo` CLI subcommand and `docs/devices/litter-robot-evo/protocol.md`, with each fact marked proven, inferred or open.

**Integration**
- **Discovery and state:** EVOs are discovered on `prod/robots/<serial>/…`. The integration reads the robot's state at startup, on reconnect and after power-on, and sets the robot's clock each time, so its sleep schedule keeps correct time even without the cloud.
- **Panel light:** the Whisker app only offers Low/Medium/High, which set the screen and status LED together. Here they're two separate sliders (1–100), plus a preset with an **Off** option that drops both to 1.
- **Other entities:** cycle delay, control lock, Sleep mode and its times, the cycle and maintenance buttons, power, status, pet weight, cycle counts, and drawer and bonnet sensors.
- **Blueprint:** keeps chosen night and day levels across a time window and puts them back after the robot reconnects (the Whisker cloud resends the app's preset when that happens). It never overrides a change made by hand.

The integration's library pin still needs a release that includes the driver.

Tested on a real EVO (robot firmware v4.7.0, IoT firmware v2.6.4):
- provisioned with this branch and discovered by the integration;
- every command marked proven was sent and checked against the robot's echo;
- after an HA restart every entity filled in by itself;
- a night boundary set the night level.

Not done yet: remote reset, sending a paused empty cycle home without a panel press, cloud-free pet identification, and the weight-sensor scale.

## Sibling repo

- [ ] Ported to the sibling repo (link the PR)
- [x] Not applicable, because: Whisker-specific device support.
- [ ] Deliberate variance, recorded in `VARIANCE.md`

## Checks

- [x] Regression test that fails on the parent commit
- [x] `STANDARD.lock` still in sync (no vendored file edited in place)

- **Library:** 1634 tests pass at 99.28% coverage, with `safety.py` and the EVO modules at 100%.
- **Integration:** the suite passes at 99.81%, with `config_flow.py` at 100% and LR4 snapshots unchanged.
- **Lint and types:** ruff and mypy are clean.

## cody, 2026-11-17T14:53:31-08:00

EVO support depends on #217, which will extract the shared Bluetooth provisioning code while preserving the existing LR4 setup path. I’ll link the refactor PR here once it’s open.

## cody, 2026-11-17T15:03:38-08:00

EVO support also depends on #218. It will make unknown LR4 command types require `allow_dangerous`, so EVO and LR4 can ship with the same safety rule.

## cody, 2026-11-17T15:06:27-08:00

EVO support also depends on #219. LR4 and EVO should both allow verified setting values by default and require `allow_dangerous` for unverified values. Each model will use its own verified ranges.

## cody, 2026-11-17T16:26:05-08:00

Thanks for the EVO work, Stephan. Let’s plan to start with an opt-in preview from a whiskerless branch after #217, #218, and #219 land. I can split the patch into PRs for Bluetooth setup, the driver and command safety, Home Assistant, and the optional blueprint and examples while preserving your authorship.

The preview would start with Power off disabled. Unknown command types and unverified setting values would require `allow_dangerous`, and the docs and tests would use a clearly labeled synthetic serial.

The preview would need to be tested on a real EVO. I don’t own one, so I’d be relying on your help with that. Shared setup changes would also need an LR4 bench test. Listing EVO as community-supported would require a named EVO owner who can help reproduce bugs and test future changes.
