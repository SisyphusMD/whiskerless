# Contributing to whiskerless

Thanks for helping un-cloud Whisker devices! Bug reports, protocol captures, docs
fixes, and new-device support are all welcome.

## Dev setup

```bash
git clone https://github.com/SisyphusMD/whiskerless
cd whiskerless
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,ble]'

ruff check src custom_components   # lint
mypy                               # strict typing (the library)
pytest                             # tests
```

The `whiskerless` library targets Python 3.11+. The Home Assistant integration
runs on whatever Python your HA install uses (3.13+) and uses newer syntax
(PEP 695 type aliases/generics) accordingly.

## Repository layout

```
src/whiskerless/                 # the PyPI library (codec, MQTT, BLE, safety, CLI)
  safety.py                      # the one safety chokepoint — every send goes through it
  mqtt.py                        # async MQTT transport (shared by all devices)
  ble/                           # device-agnostic protocomm BLE provisioning
  devices/litter_robot_4/        # LR4 protocol: const, codec, models, commands, client
custom_components/whiskerless/   # the HACS integration (depends on the library)
docs/                            # protocol reference + setup + recovery guides
examples/                        # example automations + dashboard cards
tests/                           # codec / safety / command tests
```

The integration depends on the published library via `manifest.json`
`requirements` (exactly like the official `litterrobot` integration depends on
`pylitterbot`). Keep protocol logic in the library; keep the integration a thin
pipe (subscribe → push into the coordinator).

## The safety contract (please read)

A few commands can brick a control board, and one can take the robot off the
network. So **every outbound command is classified and gated by
`src/whiskerless/safety.py`**, and both the CLI and the integration funnel through it.

- `0xA3`, `0xA4`, `0xAC`, `0xAD` (reset / main-board-OTA orchestrator, globe-motor
  OTA, flash erase, hardware reset) are **refused unconditionally** — there is no
  override flag. Do not add one. The destructive panel combos (factory reset, plug
  pull, onboarding) are refused on the same terms.
- The routine panel presses — clean cycle (`0x02010201`), reset (`0x02010401`), empty
  (`0x02010801`) — are **safe and ungated**. Writing `0x01` reproduces the exact code
  the panel emits, so it is the same event as someone pressing the button, and the
  firmware's interlocks sit downstream of it either way. There is deliberately no
  `allow_motor` flag; if you are tempted to add one back, read the note in
  `safety.py` first.
- Power (`0x02010101`) needs `allow_dangerous`. It toggles, and a robot switched off
  has left the network, so nothing over MQTT can bring it back.
- Untraced / control-band / calibration writes are refused unless explicitly
  allowed.

If you add a new command, classify it in `safety.py` and add a test. Never send a
raw opcode that bypasses the guard.

## Adding another Whisker device

The library is structured so a new robot drops in alongside `litter_robot_4`:

1. `src/whiskerless/devices/<x>/` with the same shape:
   `const.py` (registers/opcodes/topics), `codec.py` (wire encode/decode),
   `models.py` (typed state), `commands.py` (command catalog), `client.py`
   (push client). Reuse the shared `mqtt.py`, `safety.py`, and `ble/`.
2. `custom_components/whiskerless/devices/<x>.py` for device metadata
   (`DeviceInfo`), plus entity descriptions in the platform files.

Keep everything **async** and **fully typed** (mypy strict for the library), and
follow the Home Assistant platinum patterns (`DataUpdateCoordinator` as a push
state container, `runtime_data`, `EntityDescription` with `value_fn`/`set_fn`
callables, `strings.json` translations, `quality_scale.yaml`).

## A couple of design notes

- **No options flow, on purpose.** The integration rides on Home Assistant's MQTT
  integration and discovers robots, so the config flow collects only a display
  name — there are no broker/connection settings to keep anywhere. The robot's
  behavior settings (night light, wait time, schedule, lockout) are exposed as
  *entities*, the modern HA surface. Nothing belongs in `entry.options`, so there
  is no options flow.
- **Entity-removal migration.** HA tears down a device and its entities
  automatically when you remove a config entry, but it does **not** auto-clean an
  entity that a new release *removes or renames*. The first time we drop/rename an
  entity `key`, add an `async_migrate_entry` (or an entity-registry sweep in
  `async_setup_entry`) that deletes the obsolete `unique_id`
  (`{serial}_{old_key}`). Until then there's nothing to migrate.

## ⭐ The big contribution ask: confirm the two untested writes

Every panel action is now decoded — clean cycle, reset, waste-drawer reset, empty and
power are all button presses written to register `0x01`. But **empty (`0x02010801`)
and power (`0x02010101`) have only ever been *captured*, never *written*.** Both ship
as disabled-by-default buttons for exactly that reason.

If you are willing to spend an empty cycle, enable the button, press it once, and
tell us whether the robot behaved like a physical Empty press. That single trial is
the whole ask. This project has twice mistaken a captured emission for a proven
write, so the distinction is not pedantry.

Please don't guess unlisted button bits by writing them: a factory reset is two bits
from the clean cycle, and long presses are declined by the firmware anyway, so
probing tells you nothing you could not get by pressing the physical button and
reading the code off the wire.

**A note on what does not work.** This page used to say you could subscribe to your
own broker's command topic and press the button in the Whisker app. You cannot: a
cloud-paired robot talks to *Whisker's* AWS broker, so nothing reaches yours, and
intercepting it means breaking a mutual-TLS session pinned to Amazon's root with a
factory device key that provisioning never touches.

There is still a **zero-risk contributor path**, and it needs no firmware work and no
soldering:

1. Re-provision a robot onto your own broker (you've done this already to use whiskerless).
2. Watch its ACTIVITY topic, e.g.
   `mosquitto_sub -h <broker-ip> -p 8883 --cafile ca.crt -t 'prod/LR4/LR4Cxxxxxx/#' -v`
   (do not use the robot's serial as your client id — it collides and disconnects the robot)
3. Press one **physical panel button**, and note the wall-clock time.
4. The robot reports what it did as `0xRRVVVV` activity events. Tie the event to the
   action by its timestamp. This is exactly how register `0x01` (panel button events)
   was found.

For the semantics behind a value, a robot still on the cloud will give you Whisker's
own field names and enums through Home Assistant's `litterrobot` integration:
*Download diagnostics*. That is how `optimalLitterLevel` and the cycle-phase names were
pinned. It gives you meaning rather than the raw register, so pair it with a local
capture of the same action.

Open a **Protocol finding** issue with what you captured (action, payload,
firmware version). That single capture closes a gap for everyone. See
[`docs/devices/litter-robot-4/compatibility.md`](docs/devices/litter-robot-4/compatibility.md).
