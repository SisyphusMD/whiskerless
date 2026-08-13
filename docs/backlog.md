# Backlog

The project's working task list. Numbering is historical (it began life in a
working session's task tracker) and is kept stable because commits, docs and
review notes cite these numbers — do not renumber. New tasks append at the end.

Statuses: **open** (nothing started), **blocked** (says on what), **discuss**
(needs a design conversation before any code).

---

## Open

### #13 — Confirm the empty and power writes on hardware — *blocked: hardware press*

Enable the disabled-by-default buttons and press each once. Empty: `0x02010801`,
costs a litter refill. Power: `0x02010101`, toggles, needs a physical press to
undo. Both are currently inferences from captured emissions.

### #14 — Capture robotStatus during the empty-cycle confirmation — *blocked: same press as #13*

Same press as the empty-cycle confirmation, so arm a capture first. We have the
slug `empty_cycle` (cloud string `robot_empty`) but no local integer, and
`empty_cycle` is in `CLEANING_STATUSES` — so without the int, litter readings are
published from a tumbling globe. Also worth watching `odometerEmptyCycles`
(`0x3F`) increment.

### #15 — Analyze the rolling LR4 capture (ongoing)

Rolling LR4 capture analysis (pod `lr4-capture` in namespace `homeassistant`).

Fourth pass 2026-08-10/11 covered 12h19m (14:18Z–02:37Z), 1346 records,
1346/1346 JSON, 0 orphans, 0 restarts.

METHOD RULE, learned the hard way: time everything by the payload's own
`timestamp` and dedupe on (payload time, register, value). Passes 1–3 used MQTT
arrival stamps, which shifted cycle boundaries by seconds, inflated every
activity count and hid that `-30` fired twice in one cycle.

While the pod is alive with 0 restarts, `kubectl logs --timestamps --since=Nh`
beats the Loki export outright. Use Loki only across a restart or past the
container log.

Each pass has corrected the one before it — treat every conclusion as
provisional. Still uninterpreted: `0x33`, `0x3C`, `0x49`, `0x4A`, `0x5E`,
`0x64`, `0x66`; the `0x10`/`0x20` field in `0x37`; what `0x3402C0` counts; why
the pre-cycle marker alternates `0x10xx` vs `0xE065`. Still nothing above `0x7F`
in 12h19m.

### #19 — Ask Brent what differs between two LR4s whose MAIN BOARD firmware differs — *blocked: Brent*

Premise corrected twice. Original: "0xBC is firmware-gated, confirm auto-enable
on 1.4.4". Then 2026-08-11: "not firmware-gated, two robots on one build
disagree". BOTH wrong — the ESP versions match (1.1.75) but the main-board
versions do not: mbRevision 89 vs 93, mbBuild 1 vs 2, mbRevisionId 41027 vs
41088. A firmware explanation is back on the table for `0xBC`/`0xB9`, `0x0C` and
the `0x57` asymmetry. Ask Brent for his mbRevision/mbBuild alongside
espFirmware, since espFirmware alone does not identify a robot's behaviour.

### #20 — Keep the lr4-capture pod running, and tear it down when the questions close

The capture stays up for weeks rather than a single day, because several open
questions can only be answered by a rare event landing inside a capture window
(#16 hopper flap, #21 daily state-request dropout, #15 more clean cycles for
`0x3C`/`0x66`).

Loki retention is 720h (30 days), so the useful window is a rolling month —
findings must be written into `docs/devices/litter-robot-4/capture-notebook.md`
as they are found, not left to be re-derived from logs that will age out.

It is a diagnostic, not permanent: it holds an extra port open on the mosquitto
Service and a CiliumNetworkPolicy pair in the homeassistant namespace. When
#15/#16/#21 close, delete `apps/homeassistant/app/lr4-capture` and revert the
additive mosquitto Service port and ingress rule.

### #21 — Investigate the recurring "did not respond to a state request" dropout — *blocked: waiting for it to fire again*

Negative result 2026-08-10 over a clean 8h25m window (one pod, 0 restarts): 277
state requests (`0x02A00000`), 277 answered within 30s. Reply latency median
2.0s, p90 5.0s, max 11.0s. Zero gaps over 6 minutes between consecutive state
messages; the largest gap was 303s, which is the 5-minute heartbeat itself.

The dropout does not reproduce under ordinary conditions and is not a steady
background rate. Next time it fires, grab the wall-clock time and correlate
against the capture rather than trying to provoke it.

### #22 — Verify the panel sleep/wake write path live — *blocked: hardware session*

The weekday sleep schedule writes a per-day bitmask (`0x1D`) and the panel
sleep/wake times are read-only mirrors of today's weekday pair. The
write-and-verify path retries because the robot commits those registers with
latency. Never exercised live since the bitmask fix. Install a current rc on the
real robot, set a weekday schedule from the HA UI, and confirm the mask lands on
the days chosen (not just Sunday) and that the read-back verification settles
rather than exhausting its retries.

### #23 — Weigh the other two cats to settle the catWeight divisor — *blocked: narrated visit*

Settle the catWeight divisor. The shipped decoder uses ÷100 (the rc.7
revert: owner-attributed household range ~8-12 lb); ÷50 was the earlier
adoption this evidence unseated, and the narrated visit below is what
settles it for good.

Capture 2026-08-10/11 produced three distinct raw values, deduped by payload
timestamp: 914, 809 (redelivered twice), 1095. Under ÷50 that is
18.28 / 16.18 / 21.90 lb; under ÷100 it is 9.14 / 8.09 / 10.95 lb.

The tension: ÷50 was adopted on ONE comparison — raw 408, twice, for the ~8.1 lb
cat (408/50 = 8.16). None of the three new readings is near 8.1 under ÷50; one
is 8.09 under ÷100. But ÷100 turns that old raw 408 into 4.08 lb, which is what
÷50 was adopted to fix. Note 809 ≈ 2 × 408 (1.983), so the two may be one animal
on two scalings.

CRITICAL: do not infer "three values = three cats". Five visits happened; one
cat visiting repeatedly produces multiple readings too.

What actually settles it: a NARRATED visit — put a known, scale-weighed cat in
the globe and note the wall-clock time, then read the raw `0x09` for that
timestamp out of the capture. Weighing the other two cats helps but does not by
itself attribute any reading.


### #39 — Physical-action instructions are wrong or vague ("press the Connect button")

The CLI tells the user to do something that does not work
(`cli.py`: "press the robot's Connect button to enter pairing mode"). A press
does nothing — the button must be HELD (~3 seconds; confirm the duration) until
the light pulses YELLOW. A user who follows the instruction literally concludes
the tool is broken — which happened live on 2026-08-11.

`docs/recovery.md` is closer but unverifiable: "until it indicates pairing
mode" names neither the colour nor the behaviour.

Audit EVERY physical instruction in the CLI, docs/ and the HA integration, and
for each state: the exact action (press vs hold, how long), what the robot does
when it worked (light colour, behaviour, sound), and what to do if it does not.
Known starts: the pairing-mode line, recovery.md, the filter wizard, the
drawer, reset/power presses, and calibration ("fill the globe to the line" — to
WHICH line?). An instruction that is confidently wrong is worse than a missing
one.

*2026-08-13 progress:* the known-wrong pairing instruction is fixed everywhere
it appeared — the CLI and recovery.md now say HOLD until the light pulses
yellow. What remains is the full audit (exact hold duration, the filter wizard,
the drawer, calibration's "the line") and what-success-looks-like descriptions.

### #43 — DISCUSS: how users replace the Whisker app's notifications

Going local silently loses every push notification the Whisker app sent.
Confirm the app's real list first (drawer full, cat visit, cycle complete,
cycle faulted, bonnet removed, globe motor fault, hopper empty, offline). Most
raw material already exists as entities; the gap is that nobody is told what to
do with it.

The design question — (a) ship BLUEPRINTS (the sanctioned HA way; probably
right), (b) document example automations only (cheapest; `examples/` already
starts this), (c) build notification logic into the integration (almost
certainly wrong — integrations expose entities, users own automation).

Also decide FIRST: should the integration fire real HA EVENTS for momentary
things (visit ended, cycle completed, fault raised)? A flipping binary_sensor
is awkward for momentary events, and the choice changes what a blueprint can be
written against. Do not start building until the shape is agreed.

### #44 — DISCUSS: can we ever offer firmware updates? (collides with a safety invariant)

`NEVER_SEND_OPCODES` refuses `0xA3` (reset/OTA orchestrator) and `0xA4`
(globe-motor OTA) unconditionally, with no override by design. Firmware update
is, on its face, exactly the capability that list exists to deny — so this is a
proposal to revisit a core invariant, not a feature request.

Stakes are higher off-cloud: a half-applied OTA may have no recovery path, BLE
re-provisioning does not reflash firmware, and the update dispatch lives in a
bootloader region absent from every public OTA image.

Establish in order: (1) VERIFY the premise — does pylitterbot actually update
firmware, or only surface that the cloud is doing one? Read it, don't assume.
(2) If cloud-performed, the honest local answer may be a report-only `update`
entity. (3) Can we even read a published "latest version" without the cloud?
(4) Only then: whether applying is achievable AND safe, with a recovery story —
no recovery story means no, regardless of feasibility.

Defensible interim: expose the firmware versions we already decode, document
that updates require re-onboarding to the Whisker app, ship no install path.

### #45 — Confirm 0x32 is the sleep flag and work out what 0x4C is — *blocked: live toggle / rare event*

Both are one-capture observations (23h37m), so they live in the capture
notebook rather than registers.md.

`0x32`: `0x320001` fired 5s before sleepStatus went 1, `0x320000` 5s before it
went 0; only two emissions in the window. To confirm: toggle panel sleep by
hand and watch whether `0x32` tracks it (doubles as #22's live verification).

`0x4C`: nine `0x4C0001` emissions, every one during a cat visit while the robot
was asleep, then `0x4C0000` at wake beside the `0x32` clear. "A cycle is owed"
fits, but so does "a visit happened while asleep". To separate: catch a
deferred cycle with sleep off (bonnet-removed or drawer-full hold) and see
whether `0x4C` sets.

Also unexplained: a single `0x710001` thirteen minutes before sleep began.

### #49 — Record WHAT proved each detection, so the sweep stops needing a global revision counter

`DETECTION_RESET_REVISION` is a blunt instrument: it cannot tell which
sightings a rule change invalidates, so every bump re-sweeps every install.
That caused a real regression on 2026-08-12 — revision 2 retired 0x57-granted
hoppers and took genuinely-proven ones with them; revision 3 patches it by
seeding from a fill gauge. Better shape: store the evidence kind alongside each
sighting (e.g. `hopper_seen_by: "dispense" | "link"`), then a rule change
invalidates only sightings whose evidence is now unacceptable — no global bump,
no collateral, and the sweep's intent becomes readable.

*2026-08-13 review note:* do this WITH #54, not before or after — the
per-sighting evidence payload is exactly the shape of the side-effect record
the derive-reducer returns, and doing it HA-side first means moving it twice.

### #51 — Probe whether mqtt-config / whisker-config expose a READ for certs and endpoints — *blocked: robot in pairing mode*

The mapped provisioning message set is write-only for config; the single
exception is `whisker_device_id_request`, which proves the whisker-config
endpoint answers reads. A GET for the root CA, host or topic endpoints may
exist unmapped — we inferred write-only from what we implemented, which is not
the same as the firmware not offering it. Probe the message-type space on both
endpoints against a robot in pairing mode (read-only, no writes). A read would
make a pre-provisioning snapshot possible and would reveal Whisker's own AWS
endpoint hostname — the one value blocking a self-contained
`whiskerless restore-cloud` that does not depend on the Whisker app.

### #52 — Use the device-id read to verify (or supply) the serial — *blocked: one observation*

`provision` already reads the device id over BLE before writing anything, and
`_format_mac` already handles a non-MAC response: 6 bytes becomes a hex MAC,
anything else is decoded as UTF-8. So if the factory device id is the serial
string, `read_device_mac` returns it today — under a misleading name, printed
as "(MAC …)", never compared against what the user typed.

Two changes, in value order: (1) VERIFY — refuse to proceed when a
serial-shaped read disagrees with `--serial` (a typo or wrong-unit pick
currently writes the wrong client id AND topics, with no symptom but silence).
(2) AUTO-FILL — make `--serial` optional when the read supplies it, collapsing
#31 and the rest of #32.

BLOCKED ON ONE OBSERVATION: nobody has recorded what an unprovisioned LR4
returns here (both owned robots already had their client id set to the serial).
Cheapest check: next pairing-mode window, `whiskerless provision --dry-run` and
read the "(MAC …)" line. Second candidate: the BLE advertised name, which
`transport.py` already captures. Note the docs currently disagree with each
other (provisioning README says serial, recovery.md and the code say MAC) —
this observation settles that too. Renaming `read_device_mac` is a library API
break to fold into the next breaking release.

### #54 — Lift derived state out of the HA coordinator into the library

`coordinator.py` (918 lines) holds the LR4 derived state: cat weight, visit
start/duration, hopper link + last dispense, learned litter/hopper scales,
drawer last moved, globe motor fault, the beam-broken window, the scale-loaded
window, detection sightings. CLAUDE.md's architecture says the library owns
protocol logic and the integration stays a thin pipe; the coordinator drifted
past that, and the cost is that the CLI cannot show anything HA shows without a
second implementation.

Target: transport-agnostic `src/whiskerless/devices/litter_robot_4/derive.py` —
in: parsed messages + previously-learned calibration; out: derived values and
events. Pure, no I/O, no HA imports. The library owns LOGIC; Home Assistant
keeps owning PERSISTENCE (config entry options, the sweep, RestoreEntity).

Gates: 99% both suites, safety.py and config_flow.py 100%, both mypy
invocations. Entity-visible behaviour must not change; the integration tests
are the contract. Unblocks #55 and any future daemon.

*2026-08-13 review decisions:*
- Design it as a REDUCER — `(DerivedState, message, now) → (DerivedState,
  effects)` — where effects ("persist learned", "record sighting X") are
  returned, not performed. The coordinator's reported-flags structure already
  has this shape.
- Unify on ONE injected wall clock. The current wall/monotonic split exists
  only for the dedupe windows and forces the reload bridge in coordinator
  `__init__`; going all-wall deletes the bridge and fixes the
  monotonic-zero-at-boot sample loss.
- Replace the field-by-field sighting bootstrap with `DerivedState`
  to/from-dict (kills the `CONF_HOPPER_FILL_RAW` clobber).
- The split must also claim the derivation stranded in `binary_sensor.py`
  (excess-weight rule + threshold, globe-fault merge policy, hopper-empty
  floor rule) and give the restored latches an input path into the reducer.
- The press-echo watch (`_awaited_press`) is transport; it stays behind.
- FIRST, before moving code: add the two missing contract tests — the
  learned-LITTER coordinator wiring and the two-point calibration path have no
  integration test today (see #60).
- Do #49 in the same change.

### #55 — Close CLI/HA equivalence (status view, panel-reset, calibrate) — *blocked on #54*

Audited 2026-08-13 against the shipped HA surface.

WRITE DIRECTION — 3 gaps of 16: `panel_reset` (builder exists, CLI never wired
it); `calibrate_litter_empty` / `calibrate_litter_full` (they persist a
reference reading; the profile store (#53) now gives the CLI somewhere to put
it). Everything else already has a CLI equivalent.

READ DIRECTION: `whiskerless state` prints raw firmware fields; HA presents 14
sensors + 8 binary sensors (panel sleep mode joined as a binary sensor when
its always-failing switch was retired), mostly derived. Add a `status` subcommand rendering
the same derived view via #54's derive.py; keep the raw dump for protocol work.

Do NOT implement by porting coordinator logic into cli.py — that recreates the
two-implementation problem.

*2026-08-13 scope decision:* equivalence is scoped to what a one-shot can
honestly know. `status` shows everything derivable from a fresh state document
plus stored calibration; the CLI persists MANUAL calibration in the profile
store (a snapshot a human vouches for — a natural one-shot operation). The
24/7-derived facts (cat weight, visit history, learned scales, last dispense)
stay HA-only until a daemon exists to listen continuously; the CLI does not
grow a parallel derived-state store, which would duplicate and disagree with
HA's.

---

## Added 2026-08-13 (from the whole-repo cold review)

### #56 — Close the beam-gate window that can drop real visit closes

`_beam_broken_at` is stamped only by state documents showing occupancy, but the
visit-close grace is 90 s while state documents arrive on multi-minute cadence.
The freshness chain (activity → throttled refresh → state doc) is skipped
entirely while the write lock is held, and a settings write holds it for up to
~24 s of verify timeouts. A lingering visit, or one spanning a write
transaction, silently loses `CatVisitEnded` — no duration, no visit stamp, and
on a not-yet-sighted robot the detection itself. (The 300 s duration cap
explicitly admits visits three times longer than the grace.) Options: stamp the
beam from activity-stream catDetect readings too, lengthen the grace, or gate
on "beam seen since the last close" rather than a fixed window. Fold into #54's
reducer design if timing allows.

### #63 — provision should collect (and store) the broker username

`username` is a stored profile field, but provision never asks for it — on an
authenticated broker the advertised bare commands fail until the user passes
`--username` every time or hand-edits `profile.json`. Prompt for it (optional,
enter-to-skip) during provisioning, offer the value the saved robots share the
way host/CA/SSID are offered, and keep the password per-run as designed.

### #64 — translate BLE-stack errors at the library boundary

`bleak.exc.BleakError` from `scan()` / `provision_robot()` escapes to the CLI
raw, so a Bluetooth failure during provisioning still ends in a traceback. The
CLI cannot catch it by type — `bleak` is the optional `[ble]` extra and must not
be imported unconditionally — so wrap the bleak entry points in `ble/` and raise
`ProvisioningError` with the original message, exactly as the MQTT link wraps
its connect errors.

---

## Done (archive)

- #1 Capture Cycle long-press (press-type verification)
- #3 Merge PR #9's decoding, drop its filter-change button
- #4 Document tonight's protocol findings
- #5 Cut rc.3
- #6 Document the drawer-bay limitation and how to improve it
- #7 Commit the drawer-bay movement-sensor swap
- #8 Comment on GitHub PR #9 explaining why the long press cannot work
- #9 Close GitHub PR #9 pointing at the Forgejo commits
- #10 Sweep the repo for stale info, fear-mongering and dead research
- #11 Write CHANGELOG entries for everything since rc.2
- #12 Ship the empty cycle as a command (library, HA button, CLI)
- #16 Fix hopper_connected reading unknown most of the time
- #17 Decide the fate of last_visit_duration (0xBC)
- #18 Refresh the persisted hopper snapshot
- #24 Decode catDetect as a bitfield (bit 0), not truthiness
- #25 Cut rc.4
- #26 Fix the rc.4 Linux binary and Homebrew publish failures
- #27 Port whiskerless packaging to match dreame-valetudo
- #30 `--version` flag
- #32 Serial validation no longer accepts the model number
- #34 provision: no traceback on `~` paths; inputs validated at the prompt
- #35 Expand `~` in every filesystem path the CLI accepts
- #36 Real CLI error handling instead of tracebacks
- #40 Dry-run marks what it did not perform
- #41 Bare `whiskerless` prints an orientation, not usage
- #42 Capture analysis filters by serial (two robots)
- #46 `_hopper_connected`: 0x57 unusable as a link signal
- #47 Phantom visits under 300 s no longer publish as real cat visits
- #48 Fold the 2026-08-11 experiment night into the docs
- #50 pylitterbot status names are candidates for unmapped ints, not a bound
- #53 Per-machine robot profile store (`~/.whiskerless`)
- #28 GitHub `~`→`.` rewrite: **decided 2026-08-13 — accepted and documented** in packaging/README.md ("Release asset naming"); the internal package versions are unaffected and Forgejo serves canonical names
- #29 Homebrew formula unbuildable: **fixed 2026-08-13** — formula closure pins bleak<3 (homebrew-resources.py), both formulas regenerated, and `test-homebrew-formula.sh` + `homebrew-smoke.Dockerfile` now install the rendered formula from the local sdist in publish.yml before the tap moves. The smoke is linuxbrew-only; a macOS formula smoke remains unbuilt (the resource closure's platform split is small, and the failure class that shipped was cross-platform). The blocked Brewfile entry in ~/repos/cody/macos can land after the next release ships the fixed formula
- #31 label-line docs: **done 2026-08-13** — README quickstart shows both label lines side by side; the provision prompt and `--serial` help name the unhyphenated form and warn off the model number
- #33 asset naming: **done 2026-08-13** — raw binaries and .pkg now carry the version (`whiskerless-<version>-linux-x86_64`, `…-macos-arm64.pkg`), x86_64/arm64 declared the project vocabulary, scheme published in packaging/README.md
- #57 diagnostics: **done 2026-08-13** — derived facts and entry options included, test updated
- #58 device sw_version: **done 2026-08-13** — the coordinator updates the device registry when a state document carries a new espFirmware
- #59 coordinator nits: **done 2026-08-13** — night-light verifies against the clamped value, an empty cycle with no odometer baseline trusts the echo instead of a doomed fetch, and messages landing mid-unload are dropped (the press false-confirm remains documented-only, value equality cannot distinguish source)
- #60 Phase 2 contract tests: **done 2026-08-13** — the learned-litter wiring (dedupe, promotion, persistence, 90% anchor) and the two-point calibration path (both buttons pressed for real, 40% at the fixture reading) are pinned in test_coordinator.py
- #61 release coverage gates: **done 2026-08-13** — release.yml and prerelease.yml now run the same --cov-fail-under=99 + safety/config-flow 100% gates as ci.yml (the lowest-deps floor job stays plain on purpose)
- #62 GLIBCXX check: **done 2026-08-13** — the checker now holds GLIBCXX/CXXABI to the floor-era ceilings (GCC 8 for glibc 2.28) via an explicit table that fails loudly on an unknown floor
- #37 terminal UX: **done 2026-08-13** — `src/whiskerless/console.py` (stdlib-only): per-stream color gating with NO_COLOR/TERM=dumb, a live spinner+elapsed progress row for the BLE scan (heartbeat when piped), danger banners on the empty/power prompts, and colorized monitor/state output. Deliberately NOT ported from dreame: prompt bookmarking and idle timeouts (tmux-workflow machinery whiskerless has no equivalent of) and die()/abort() (the CLI already has its exception→exit-code architecture)
- #38 README: **done 2026-08-13** — restructured around the guided flow (an honest abridged transcript up front), "What you need" with the label-line diagram, per-platform install sections including Homebrew, "Provision the robot" with the hold-until-yellow instruction, Everyday use, Upgrading, Release candidates (and switching back), Uninstalling
