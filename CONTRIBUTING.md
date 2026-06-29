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

Some commands drive a motor, and a few can brick a control board. So **every
outbound command is classified and gated by `src/whiskerless/safety.py`**, and
both the CLI and the integration funnel through it.

- `0xA3`, `0xA4`, `0xAC`, `0xAD` (reset / main-board-OTA orchestrator, globe-motor
  OTA, flash erase, hardware reset) are **refused unconditionally** — there is no
  override flag. Do not add one.
- No motor command is exposed: no opcode is yet proven to drive the globe (the old
  `0xA3` guess turned out to reset the robot). The `MOTOR` / `allow_motor` gate stays
  wired for a future, confirmed cleanCycle trigger.
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

## ⭐ The big contribution ask: crack the unsolved actions

**Power on/off, the empty cycle, and the panel/drawer resets are not yet
supported.** Reverse-engineering couldn't pin their exact `register+value` to
safe, actionable confidence — the firmware partition that handles those inbound
commands is physically absent from the public image, and the candidates are
unproven and contradictory. We won't ship guesses that could trigger a dangerous
control-band write.

There's a **zero-risk way to solve them** that needs no firmware work and no soldering:

1. Re-provision a robot onto your own broker (you've done this already to use whiskerless).
2. Subscribe to its command topic, e.g.
   `mosquitto_sub -h <broker-ip> -p 8883 --cafile ca.crt -t 'prod/LR4/LR4Cxxxxxx/command' -v`
3. In the **official Whisker app**, press **Power off / Power on / Empty / panel
   Reset**, one at a time.
4. The cloud publishes the literal `{"serial":...,"data":["0x02RRVVVV"]}` for each
   button. **That payload is the answer.**

Open a **Protocol finding** issue with what you captured (action, payload,
firmware version). That single capture closes a gap for everyone. See
[`docs/devices/litter-robot-4/compatibility.md`](docs/devices/litter-robot-4/compatibility.md).
