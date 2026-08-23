# Contributing to whiskerless

Thanks for helping un-cloud Whisker devices! Bug reports, protocol captures, docs
fixes, and new-device support are all welcome.

## Dev setup

```bash
git clone https://github.com/SisyphusMD/whiskerless
cd whiskerless
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,ble]'

ruff check src custom_components tests packaging   # lint
mypy                               # strict typing (the library)
pytest                             # tests
```

The `whiskerless` library targets Python 3.11+. The Home Assistant integration
runs on whatever Python your HA install uses (3.13+) and uses newer syntax
(PEP 695 type aliases/generics) accordingly.

### Integration tests

`pytest` above runs the library tests only — the root conftest skips
`tests/integration` when Home Assistant is not importable. Home Assistant needs
its own Python, so give it a second environment rather than fighting the first:

```bash
uv venv --python 3.13 .venv-ha          # uv fetches 3.13 if you haven't got one
# `test-ha` alone, plus the type-checker. The Home Assistant harness pins pytest,
# pytest-asyncio and pytest-cov to exact versions of its own, and `dev` pins the same
# three exactly — asking for both extras cannot resolve. Same split CI uses.
VIRTUAL_ENV=.venv-ha uv pip install -e '.[test-ha]' \
  "$(grep -oE '"mypy==[0-9][0-9a-zA-Z.+-]*"' pyproject.toml | tr -d '"' | head -1)"

.venv-ha/bin/python -m pytest tests/integration --cov --cov-report=term-missing
.venv-ha/bin/python -m mypy --strict --python-version 3.13 --namespace-packages \
  --explicit-package-bases custom_components/whiskerless
```

CI gates four coverage numbers, so check them before opening a PR:

| Scope | Floor | Why |
|---|---|---|
| `custom_components/whiskerless` | 95% | the quality scale's `test-coverage` |
| `custom_components/whiskerless/config_flow.py` | 100% | `config-flow-test-coverage` |
| `src/whiskerless` | 98% | BLE is faked at the `bleak` boundary rather than skipped |
| `src/whiskerless/safety.py` | 100% | every send funnels through it |

Entity changes will fail the snapshot test, which is the point — regenerate with
`--snapshot-update` and **read the diff**. An entity that changed name, device
class or unit without you meaning it takes the user's dashboards with it.

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
   `models.py` (typed state), `commands.py` (command catalog), `link.py`
   (connected session). Reuse the shared `mqtt.py`, `safety.py`, and `ble/`.
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

## Licence, and why this one

**MIT.** Contributions are accepted under it.

The reasoning, written down so it is not re-argued:

- **Permissive, because this is a library imported into Home Assistant.** The integration declares
  `whiskerless==<version>` and Home Assistant installs it from PyPI, so the library runs *inside*
  HA's own process. HA Core is Apache-2.0 and is network-served by definition — its whole product is
  a web UI. A copyleft licence here would reach the combined work: anyone shipping an HA appliance
  image, or running HA for other people, would owe source for it. MIT removes that question.
- **It also keeps the door open.** Home Assistant Core does not accept copyleft dependencies. The
  official `litterrobot` integration depends on `pylitterbot`, which is **MIT** — the exact model
  this project is built on. Anything stronger closes that path permanently, on day one.
- **The sibling is copyleft, deliberately.**
  [dreame-valetudo](https://github.com/SisyphusMD/dreame-valetudo) is GPL-3.0-or-later because it is
  a standalone tool that nothing imports, so none of the above applies and copyleft costs its users
  nothing. Same question asked twice, two different correct answers — see its `CONTRIBUTING.md`.

**Consequence to keep in mind:** code can flow from this repo into the sibling, never the other way.
Anything genuinely reusable should be written here, or in the shared `project-standard`, rather than
there.

## Where issues and pull requests go

**GitHub.** Open them at [SisyphusMD/whiskerless](https://github.com/SisyphusMD/whiskerless) — it is also the mirror HACS installs from, so it is where users already are.

Forgejo (`forgejo.bryantserver.com/SisyphusMD/whiskerless`) is the source of truth and runs the full CI
suite on every push to `main`, but it is not where contributions arrive — outside contributors have
no account there, and its runner holds this project's release credentials. Every job in
`.forgejo/workflows/ci.yml` therefore carries a fork-trust gate and deliberately **skips** a pull
request from a fork rather than running untrusted code beside those secrets.

So a fork PR is tested on **GitHub-hosted runners**, which hold none of our secrets, by
`.github/workflows/ci-pr.yml`. You get lint, strict type-checking of both the library and the integration, both test suites at their 99% floors, the `safety.py` and `config_flow.py` 100% gates, the declared dependency floors, shellcheck, and documentation links.

**What that does not cover**, so you are not surprised by a later failure:

- **The install matrix.** 25 install channels across five distributions run on
  Forgejo and at release time, not per-PR — a packaging change can pass here and fail
  there.
- **macOS and bottles.** Both need runners this workflow does not use.
- **Hardware.** Nothing in CI touches a robot. The BLE transport is faked at the `bleak`
  boundary and no runner has a radio, so provisioning changes need a bench run.
- **Safety classification is not a style question.** Any new command must be classified in
  `safety.py` with a test. Do not add an override flag for `NEVER_SEND_OPCODES`.

The sibling project works the same way, for the same reasons — see its `CONTRIBUTING.md`.

## What this project promises not to break

Two surfaces, and they are promised differently because they have different consumers.

### The Python API — a compatibility promise

Home Assistant installs this library from PyPI and the integration imports it, so a rename here
breaks software already running on other people's machines. What is promised:

- **`whiskerless`** — everything in its `__all__`.
- **`whiskerless.devices.<device>`** — everything in its `__all__`, including the submodules it
  re-exports (`calibration`, `commands`, `const`, `derive`, `models`, `protocol`) and the names in
  each of those modules' own `__all__`.

Everything else is internal and may be renamed, moved or deleted without notice.

**A repo invariant test enforces that the promise is at least as large as what the bundled
integration actually imports.** That is the failure mode worth guarding: the declared surface stays
small and true while the real consumed surface grows around it, so a rename that looked safe breaks
a consumer the promise said was not there. If a promise feels too large, the fix is for the
integration to need less — not for the promise to look smaller than reality.

To change a promised name: add the new one, keep the old as an alias, note the deprecation in
`CHANGELOG.md`, and remove it no sooner than the next MINOR release.

### The CLI — a compatibility promise

People script against this. Promised: **subcommand names, their flags, and the exit codes**
(`0` success, `1` error, `2` refused by the safety guard, `130` interrupted). Human-readable output
text is NOT promised — parse the exit code, not the prose.

Adding a subcommand or an optional flag is additive and needs no window. Renaming or removing one
needs an alias and a deprecation note, on the same terms as the API.

### Home Assistant entity IDs

Also a promise, and an easily forgotten one: renaming an entity silently breaks every automation,
dashboard card and history graph a user built on it. Treat `unique_id` and the entity's `key` as
frozen; the display name is free to change.

