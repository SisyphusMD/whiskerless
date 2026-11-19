# #190 feat(addon): optional robot broker for Home Assistant OS

- Kind: pull, state: closed, by cody, created 2026-11-17T08:45:10-08:00
- Labels: none; milestone: none
- refs/pull/190/head -> main, merged: False

Refs #187.

Moved from https://github.com/SisyphusMD/whiskerless/pull/16, opened by Stephan Garland (@stephanGarland on GitHub) on 2026-11-06, with his commits unchanged. **Not yet reviewed.** Sent as an AGit pull request so CI does not run unreviewed code; a maintainer re-opens it from a branch after review.

---

I split this work into three separate PRs as I wasn't sure if you'd want the bridge and broker.

## What and why

The robot connects to its broker on port 8883 without a username or password. Home Assistant OS's Mosquitto add-on requires both, so on HAOS the robot can't use it, even though the README currently suggests it can.

This adds an optional **Whiskerless robot broker** add-on (this repo also becomes an add-on repository; HACS is unaffected). It's a small Mosquitto with a TLS listener for the robot, and it bridges the robot's topics into the Mosquitto add-on, so the integration sees them as usual.

`docs/setup/robot-broker.md` covers when you need it and when you don't. It also covers what to do when something else already uses port 8883: the robot's port can't be changed, so you redirect its traffic with a NAT rule on your router. The robot then needs a fixed IP, since the rule matches on it.

Tested on a real EVO on a separate VLAN, with another service holding port 8883 on the host.

## Sibling repo

- [ ] Ported to the sibling repo (link the PR)
- [x] Not applicable, because: Valetudo can log in with a username and password, so it can use the Mosquitto add-on directly.
- [ ] Deliberate variance, recorded in `VARIANCE.md`

## Checks

- [ ] Regression test that fails on the parent commit (docs and a shell add-on; `run.sh` passes shellcheck)
- [x] `STANDARD.lock` still in sync (no vendored file edited in place)

## cody, 2026-11-17T08:59:24-08:00

_@b12e on GitHub, 2026-11-09:_

>  Home Assistant OS's Mosquitto add-on requires both, so on HAOS the robot can't use it, even though the README currently suggests it can.

No, it doesn't. But you need to change some config.

I'm running the Mosquitto's add-on on HAOS for all other MQTT things and the Litter Robot is publishing to the very same broker without issue.

in the Mosquitto addon settings in HA -> Settings -> Apps -> Mosquitto -> Config via UI:
<img width="1035" height="335" alt="afbeelding" src="https://github.com/user-attachments/assets/d7f8cbb9-6525-4e6d-9d17-f7fc34f98058" />

or as YAML:
```yaml
customize:
  active: true
  folder: mosquitto
```

And then a new file (modify to your own needs) in `/share/mosquitto/` (can access via SSH or via the VS Code addon) (I named it `whiskerless.conf`):

```nginx
listener 8883
protocol mqtt

cafile   /ssl/whiskerless/ca.crt
certfile /ssl/whiskerless/server.crt
keyfile  /ssl/whiskerless/server.key

require_certificate true
use_identity_as_username true
```

Remember to point to the correct path for your certs.

## cody, 2026-11-18T08:31:19-08:00

Thanks for testing this on an EVO with another service already using port 8883, @stephanGarland. The HAOS guide was missing the custom listener that b12e described. With #230 merged, `whiskerless setup` on `main` generates the listener file, and the guide shows how to enable it in the official Mosquitto app.

That setup still needs port 8883 free at the broker address. The redirect in this PR handles that conflict on the same host. I’m closing this PR to keep the supported HAOS setup to one broker.

https://forgejo.bryantserver.com/SisyphusMD/whiskerless/src/branch/main/docs/setup/mqtt-broker.md#user-content-use-the-official-mosquitto-broker-app
