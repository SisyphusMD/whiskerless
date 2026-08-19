# Backlog

The project's working task list. Numbering is historical (it began life in a
working session's task tracker) and is kept stable because commits, docs and
review notes cite these numbers — do not renumber. New tasks append at the end.

Statuses: **open** (nothing started), **blocked** (says on what), **discuss**
(needs a design conversation before any code).

---

## Open

### #75 — Decide whether the Linux packages should be signed like the macOS one — *DONE 2026-08-17: checksums, then GPG once the repository made it real*

The macOS `.pkg` is signed with a Developer ID and notarized;
`packaging/nfpm.yaml` carries **no signing configuration at all**, so the `.deb`
and `.rpm` ship unsigned.

This is platform-driven rather than neglect — Gatekeeper refuses an unsigned
`.pkg`, and nothing on Linux refuses an unsigned package installed directly with
`dpkg -i` / `rpm -i`. But it means a Linux user has no way to verify what they
downloaded, where a macOS user does. nfpm supports GPG signing; the question is
whether a key is worth carrying for packages nobody installs from a repository.

**Answered 2026-08-17.** Signing only does work where something verifies it
automatically — an apt/dnf **repository**, where the package manager checks every
install. These are downloaded from release pages and installed with `dpkg -i`,
which does not check signatures at all (`rpm -i` only warns if configured), so a
signature would sit unverified unless a user manually imported a key. macOS is
not the counterexample it appears to be: notarization is not a practice we
followed, it is Gatekeeper refusing to run the thing otherwise.

So `publish.yml` now ships a **`SHA256SUMS`** covering every Linux artifact,
which closes the real gap ("did this arrive intact") with no key to hold, rotate
or revoke. Its limit is stated in the workflow: served from the same host as the
artifacts, it proves integrity and not authenticity.

**Then the condition it named came true.** The repositories in #77 are exactly
the "something verifies it automatically" case, so the packages are now signed
with `4BBACD5A6FF38564` as well. On dnf that signature is what `gpgcheck` checks
on every install; on apt it stays belt-and-braces, since apt authenticates the
repository index Forgejo signs rather than the `_gpgorigin` member nfpm embeds.

### #76 — One forge failing should not skip the work for the others — *DONE 2026-08-17*

rc.27 exposed this: `publish.yml`'s release job publishes to Forgejo, the NAS and
GitHub, and when the GitHub step failed (waiting for a tag the mirror had not yet
delivered) the **whole job** failed — which then **skipped** the `nas-pkg` bridge
downstream. Result: Forgejo got all 8 assets, the NAS got 6 (no `.pkg`, because
the bridge never ran), GitHub got 2 (the `.pkg` that `release-macos.yml` attached
on its own).

Two artifacts of one design: a single job publishing to three independent
destinations, and a downstream job gated on that job as a whole. Publishing to
each forge should stand or fall on its own, and the NAS bridge should depend on
the `.pkg` existing rather than on every other forge having succeeded.

**Done 2026-08-17.** The publish step already tried each forge independently and
collected failures — the coupling was narrower than it looked: `nas-pkg` had
`needs: releases`, so GitHub's failure skipped the `.pkg` bridge entirely. It now
carries `if: ${{ !cancelled() }}`, because the only thing it needs is the `.pkg`
on the public Forgejo release, which has nothing to do with GitHub. `prune-rcs`
gained `needs: [releases, nas-pkg]` so it cannot prune while this release is
itself incomplete. The GitHub tag wait went from 10 minutes to 30, since rc.27
timed out at ten on a tag that arrived shortly after.

### #74 — Forgejo has no infra-retry, and no rerun API to fall back on

`retry-infra-failures.yml` re-runs a job when the *runner* failed before any of
our steps began — but it lives in `.github/` and watches GitHub workflows only.
Forgejo has no equivalent, and its API exposes no rerun endpoint at all (checked
against `swagger.v1.json`: `runs/{id}/cancel` exists, nothing to re-run).

Seen 2026-08-17: all five `ci.yml` jobs failed together on
`actions/setup-python` — "Failed to fetch the Python versions manifest ... all
retries were exhausted". Zero real failures; every job died in setup.

**Probably not a random flake.** The household internet was intermittently down
across that window, and the same period produced a second network-shaped
failure: `publish.yml`'s GitHub release step waited out its full ten minutes for
the mirrored rc.27 tag to become visible and gave up. Both are consistent with
the outage; neither is proven to be caused by it. The lesson holds either way —
a release cut has no tolerance for a network blip, on a forge with no retry.

Cosmetic on a `main` push, since the only way back to green is another push. It
is **not** cosmetic during a release: the same flake in a `prerelease.yml` gate
job fails the cut and needs a manual re-dispatch. Worth either a Forgejo-side
retry workflow or pinning the interpreter setup so it stops reaching out to a
manifest mid-build.

### #73 — Ship Homebrew bottles so `brew install` stops compiling cryptography — *DONE 2026-08-17*

Taking `cryptography` made the tap expensive: Homebrew builds every resource from
source, cryptography's extension is Rust, and Homebrew's `rust` formula drags in
`llvm` — so a `brew install` now downloads ~2.4 GB of build dependencies and
compiles for several minutes, on every user's machine.

**The dependency list is not the problem.** homebrew-core's `certbot` needs
cryptography too and declares exactly the same trio (`openssl@3`, `pkgconf`,
`rust`). The difference is that certbot ships a **bottle** — a prebuilt keg — so
nobody installing it ever compiles. Our tap ships none, so everyone does.

The fix is to build bottles in CI and attach them to the tap: `brew bottle
--json` per platform, upload the tarballs, add the `bottle do … end` block to
both formula templates. The runners already exist — `release-macos.yml` uses
GitHub's macOS machines for the `.pkg`, and Linux is free.

Four things settled while scoping it (2026-08-17):

- **Bottles go to GitHub, not the mirror-by-git path.** The tap repo is
  Forgejo-primary and mirrors to GitHub (verified: identical HEADs), but a git
  push-mirror replicates **refs only — never release assets**. So the formula
  mirrors for free and the bottles do not; they have to be uploaded to GitHub
  explicitly, the way `publish.yml` already attaches the `.deb`/`.rpm`/binaries
  with `GH_REPO_WRITE_PAT` — which it does for all three forges, so bottles ride
  the same path as every other artifact. (Where `root_url` then points is a
  separate question, answered below.)
- **A bottle covers the whole formula, not one resource.** It prebuilds the
  entire venv, so it removes cryptography's Rust build *and* `cffi`'s and
  `pyobjc-core`'s C builds. `rust` and `pkgconf` are `=> :build`, so bottled
  users never install them — and `llvm` (1.9 GB) is rust's dependency, not ours,
  so it goes with them. Only `python@3.14` and `openssl@3` remain.
- **One bottle per ARCH, not per macOS version.** Homebrew falls back to an
  older bottle when none matches the running OS — verified 2026-08-17 on a
  macOS **27** machine, which poured `arm64_tahoe` (26) bottles for `rust`. So
  building on the oldest supported OS covers every newer one. Note also that
  macOS 16–25 do not exist: Apple went 15 (Sequoia) → 26 (Tahoe) → 27, so the
  matrix's `macos-15` "floor" and `macos-26` "current" are *consecutive*
  releases. Building the floor leg gives `arm64_sequoia` + `sequoia`, and 26 and
  27 both use them.
- **Four bottles total, then**: `arm64_sequoia`, `sequoia`, `x86_64_linux`,
  `arm64_linux`. The Linux formula smoke runs on an **arm64** runner while
  GitHub's ubuntu runners are x86_64, so Linux needs both — and Homebrew's
  well-trodden Linux path is x86_64.
- **`root_url` is a free choice, not a constraint.** HACS genuinely requires
  GitHub; Homebrew does not — `root_url` takes any HTTPS URL, so pointing it at
  Forgejo keeps the primary-forge convention. The cost is availability: once a
  bottle exists, brew stops fetching the PyPI sdist, so whatever `root_url`
  names becomes the *only* download path for every install anywhere.

The alternative that avoids per-OS bottle maintenance entirely is installing the
compiled resources from upstream wheels instead of building them. It departs
from Homebrew's source-build convention, which is why it is not the default
recommendation — but for a personal tap serving a CLI it is defensible, and it
costs nothing to maintain as macOS versions roll.

**Done 2026-08-17.** `.github/workflows/bottles.yml` builds the four, and
`publish.yml`'s `homebrew-bottles` job writes the block in a **second** tap pass —
a bottle is produced by installing the published formula, so the block cannot
exist until after the formula does. Three things were settled by testing rather
than reasoning:

- A bottle's keg is rooted at `<formula>/<version>/`, confirmed by unpacking one,
  so a `whiskerless` bottle genuinely cannot be renamed into a `whiskerless-rc`
  one. The 8-on-stable rule is not belt-and-braces; it is the only way.
- Homebrew fetches `<root_url>/<filename>` using the single-dash `filename` from
  the manifest, not the double-dash name `brew bottle` writes locally. Proven by
  serving a generated block over HTTP and watching Homebrew pour it.
- The cellar in the manifest is a concrete path for a venv install, not `:any`,
  so the generated block quotes it rather than emitting a symbol.

`bottle-block.py` refuses a short set, a manifest from another version, and a
non-zero rebuild counter, because each of those publishes happily and only shows
up as somebody quietly compiling.

### #77 — Publish apt/dnf repositories — *DONE 2026-08-17*

Signing the packages (#75) only does real work where something verifies it
automatically, which is a repository. Forgejo 16 has native Debian and RPM
registries, so that is what `publish.yml` now pushes to, into `stable` and
`testing` distributions.

Findings that are worth keeping, all established against the live registry:

- The upload paths differ in shape between the two formats — debian takes
  `pool/{distribution}/{component}`, rpm takes a `{group}`.
- Forgejo generates a **separate key per registry type**, so `debian/repository.key`
  and `rpm/repository.key` are different keys. It stores and serves uploaded
  bytes unmodified, so our own signature on the `.rpm` survives and is what
  `gpgcheck` verifies.
- **The `.repo` file Forgejo generates cannot install our packages.** It lists
  only Forgejo's RPM key under `gpgcheck=1`, and `dnf install` fails with
  `GPG check FAILED`.
- **Naming both keys, which was the first fix, is a security downgrade.** dnf
  accepts a package signed by ANY key in `gpgkey`, so listing Forgejo's alongside
  ours means a package signed only by Forgejo's key installs — verified both
  ways. That key lives in Forgejo's database in plaintext, on the host serving
  the packages, so listing it would make one host's compromise enough to install
  arbitrary code on every subscriber. `packaging/*.repo` therefore pins **our key
  alone**, with `repo_gpgcheck=0`, and is shipped in the repo so the install is
  still a one-liner.
- **Forgejo can sign RPMs itself** (`?sign=true`, or `DEFAULT_RPM_SIGN_ENABLED`).
  Not used: it would move the anchor onto the host it protects, and make the
  registry copy of a release differ from the identical-looking file on the
  release page. Its Debian key is unavoidable, though — apt authenticates the
  index, Forgejo signs the index, and there is no API to substitute ours.
- A re-upload answers 409, which the publisher treats as success so a dispatched
  re-run of a partial publish still completes.

### #78 — `prune-rcs` reaches the package registry — *DONE 2026-08-17*

Pruning a release used to leave its packages behind, and a candidate left in
`testing` is worse than a stale release: it is still being served.

The trap, and the reason this needed hardware-in-the-loop testing rather than
reading the API docs: **the two formats rebuild their published index from
opposite endpoints.** Deleting a debian package through the pool endpoint, or an
rpm through the generic one, returns 204 and leaves the index advertising a file
that now 404s. Both directions were confirmed by deleting and then reading the
published `Packages` / `primary.xml`.

Also found and fixed while testing: GitHub answers a DELETE for a missing tag ref
with **422**, not 404, so the ordinary already-gone case aborted the whole sweep.
That was pre-existing and became reachable far more often once candidates are
also enumerated from the registry.

### #72 — `setup --ca --ca-key` files the CA but never issues the broker's server cert — *DONE 2026-08-17*

Bringing your own CA *and* its key gives whiskerless everything it needs to issue
the broker's server certificate, and it does not: `_ensure_pki()` saves the pair,
mints this machine's client identity, and returns. `setup` then prints "make sure
your broker presents a certificate signed by this CA" — true, and unhelpful when
the thing that could sign it is sitting right there. The generate-a-CA branch two
lines below does exactly this.

Two ways to read the current behaviour, which is why this is a question and not
a bug: somebody with their own CA may well have their own issuance process and
would not want a stray leaf minted for them, and issuing one silently overwrites
`broker/server.*` if they had already put their own there. A prompt ("issue your
broker's certificate too?") splits the difference. Noticed while writing
`restore`, which has to know whether those files exist before pointing at them.

**Done 2026-08-17.** `_refresh_server_cert()` now mints the first certificate
when this machine can sign and none exists, alongside reissuing one that names
the wrong host. Only ever when the file is **absent**, so a valid certificate
somebody placed themselves survives — an *unreadable* one is still reissued,
which is a different case and deliberate.

### #13 — Confirm the empty and power writes on hardware — *POWER DONE 2026-08-16; empty still blocked (costs a litter refill)*

**Power: DONE 2026-08-16.** `0x02010101` was published to a live robot; it emitted
`0x010101` and powered off, publishing for ~38 s on the way down. The physical press
that brought it back emitted `0x010101` **again**, so a written press and a finger are
the same event in both directions. Remaining half is the empty cycle only.

**Only the empty cycle is left.** Enable the disabled-by-default *Empty cycle*
button and press it once: `0x02010801`, costs a litter refill. Do NOT repeat the
power test — it is done, and running it again only takes the robot off the network
and needs someone standing there to undo it.

### #14 — Capture robotStatus during the empty-cycle confirmation — *blocked: same press as #13*

Same press as the empty-cycle confirmation, so arm a capture first. We have the
slug `empty_cycle` (cloud string `robot_empty`) but no local integer, and
`empty_cycle` is in `CLEANING_STATUSES` — so without the int, litter readings are
published from a tumbling globe. Also worth watching `odometerEmptyCycles`
(`0x3F`) increment.

### #15 — Analyze the rolling LR4 capture (ongoing)

NEW LEAD (2026-08-15): `0x5F`-`0x63` fire only in the same second as a globe-motor
fault raise, twice in five days, values `55/12`, `14/14`, `326/172`, `65520`
(`0xFFF0` = -16 int16) and `0/0`. Five unmapped registers appearing only beside a
fault look like its diagnostic payload; two samples from one fault on one robot
is a lead, not a decode. Next fault is the test.

Rolling LR4 capture analysis (pod `lr4-capture` in namespace `homeassistant`).

Fifth pass 2026-08-15 covered the whole 5d04h (08-10 14:18Z → 08-15 18:46Z),
535,778 lines, 1 malformed. Fourth pass 2026-08-10/11 covered 12h19m
(14:18Z–02:37Z), 1346 records, 1346/1346 JSON, 0 orphans, 0 restarts.

RETRIEVAL, corrected: the k8s-workerbig reboot on 2026-08-15 00:31Z made the
Deployment replace the capture pod, and the old pod object was deleted with its
log directory — so `kubectl logs` offers 17 hours and nothing earlier. (For an
ordinary container restart inside a surviving pod, `--previous` is still the
cheaper answer; this was not that.) LOKI HAS THE REST, earlier pods included — the working note saying Loki was
unusable here is wrong. Query `{namespace="homeassistant", pod=~"lr4-capture.*"}`
and page it forward (limit 5000, cursor past the newest line of each batch).

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

### #22 — Verify the panel sleep/wake write path live — *premise corrected 2026-08-16: the panel cannot set a TIME at all*

**The original premise is void.** This asked whether a schedule change made *at the
panel* shows up the same way. It cannot: an LR4 has five buttons and no screen, so the
panel can only toggle an 8-hour window on and off — it has no way to enter a time. What
was observed 2026-08-16 is that the panel DOES write `0x1B`/`0x1C` (as "now + 8 h") and
sets `weekdaySleepModeEnabled` to `0x7F`, and that exiting clears them to 0/0 rather
than restoring the previous schedule. What remains untested is our own write path
against the per-weekday registers, which is an integration test, not a bench one.

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


### #39 — Physical-action instructions — **DONE 2026-08-16**

*2026-08-13:* the known-wrong pairing instruction was fixed everywhere (HOLD
until the light pulses yellow).

*2026-08-15:* the calibration instruction stopped citing a marking nobody has
confirmed ("fill the globe to the line" → fill it the way you consider full,
since whatever level you pick becomes 90%), and the Home Assistant guide gained
a "how you know it worked" for the calibration press — the Litter reference
sensor changes, and the percentage moves only on firmware that does not publish
its own.

What is left cannot be written from a desk: the exact Connect hold duration and
what the light does, whether the globe or filter carry any marking a user could
be told to look at, and what the robot does when a drawer is pulled and reseated.
All four are in `docs/devices/litter-robot-4/bench-protocol.md`, to be answered
in one trip.

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

### #45 — Confirm 0x32 is the sleep flag — **DONE 2026-08-16, PROVEN on both robots**

**Done 2026-08-16.** Sleep mode is a hold on **Cycle**; an LR4 has no menu. On
BOTH robots the hold emitted `0x010202` and drove `0x320001`, and a second hold
drove `0x320000` — each 31+ minutes clear of the scheduled boundary, which is what
the five nights of ten-for-ten schedule matches could never establish. `0x1A`,
`0x1B` and `0x1C` moved with it, the window was exactly 8 hours on both, and
`weekdaySleepModeEnabled` went to `0x7F`. Detail in the capture notebook.

What remains under this number is `0x4C` only:

`0x4C` is NOT answered, and the five-day pass narrowed it without settling it:
54 emissions, all with sleepStatus 1, none awake; it clears at all five wakes;
a clean cycle follows within 3-5s at four of them. The fifth (night ending
08-12) had seven sets, cleared normally, and no cycle — which is what "a cycle
is owed" predicts against. The discriminating test is unchanged and still
untried: a cycle deferred while AWAKE (bonnet lift or full drawer) with a cat
visit inside the deferral. The only awake blocker in five days was a 7-second
bonnet removal with no cat, which tests nothing.

Also unexplained: `0x710001`, five emissions in five days on robot 1.

### #51 — Probe whether mqtt-config / whisker-config expose a READ for certs and endpoints — *bench work: needs a probe script written first, then a pairing window*

The mapped provisioning message set is write-only for config; the single
exception is `whisker_device_id_request`, which proves the whisker-config
endpoint answers reads. A GET for the root CA, host or topic endpoints may
exist unmapped — we inferred write-only from what we implemented, which is not
the same as the firmware not offering it. Probe the message-type space on both
endpoints against a robot in pairing mode (read-only, no writes). A read would
make a pre-provisioning snapshot possible and would reveal Whisker's own AWS
endpoint hostname — the one value blocking a self-contained
`whiskerless restore-cloud` that does not depend on the Whisker app.

### #52 — Use the device-id read to verify (or supply) the serial — **CLOSED 2026-08-16: answered, not viable**

**Answered 2026-08-16: the read returns a MAC** (`b4:8a:0a:8a:c9:28`), not the
serial. Both halves of this task rested on it being the serial, so both are dead —
there is nothing to verify `--serial` against and nothing to auto-fill it from.
The docs contradiction is settled in the same stroke: the provisioning README said
serial, `recovery.md` and the code said MAC, and the code was right.

Kept for the reasoning, since "read the device id" is an obvious idea that will
occur to someone again:

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

---

## Added 2026-08-13 (from the whole-repo cold review)

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

## Added 2026-08-16 (from the bench night)

### #67 — Adopt an existing robot into the profile store — **DONE 2026-08-16**

The profile store only writes on a **successful `provision`**, so anyone whose robots
were set up before it existed has no profiles and gets none by upgrading. They pass
`--serial/--host/--ca` forever, or re-provision purely to populate a file — and
re-provisioning is the one step that touches the robot's stored config. The owner hit
this on his own robots during the bench night, which is how it surfaced; the README
meanwhile sells "later commands run bare" as though it applies to everyone.

**Shipped as `whiskerless adopt`** — flags only, no BLE, no broker. It validates the
serial's shape and that the CA is a PEM, records the serial as UNVERIFIED (because
nothing confirmed it), does not steal the default from an existing robot, and prints
`whiskerless state` as the way to check. It cannot do better than shape-checking
offline: a typo becomes the client-id and both topic segments, and the robot that
never answers looks identical to one that is merely asleep.

### #68 — The hopper gauge under-reports

Ground truth 2026-08-16: a hopper photographed **mostly full** was published as roughly
**half**. The waste drawer (78 % reported, ~78 % observed) and the globe litter level
(~445 raw, ~67 % observed) were both accurate in the same session, so this is specific
to the hopper scale rather than a decode error. Likely the learned floor/ceiling rather
than `0x0C` itself. Needs a second narrated fill — ideally a full hopper photographed at
a known time, then a drain — to say whether the span or the floor is wrong.

**Re-measure before investigating further (2026-08-17).** Dispense detection required
the burst in one message, which the wire never sends, so **every fill-gauge sample was
discarded** — the learned scale on that robot was built from whatever RESTORED/LEGACY
evidence predated it, not from observation. Now that samples actually land, the reading
this entry is about may simply be a scale that had nothing to learn from. Take a fresh
measurement before changing the span or the floor.

### #69 — The CLI assumes the operator's machine can reach the broker — *docs done 2026-08-16*

`whiskerless state`, `monitor`, `set` and `send` all open an MQTT connection, so they
only work from a host with a route to the broker. In the setup this project
recommends — robots on an isolated IoT VLAN, broker exposed there — a normal
workstation often has no such route, and the owner's does not: `cannot reach broker at
…:8883 (timed out)` from the same Mac that provisions over BLE perfectly well.

Nothing is broken, but the README's "everyday use" section reads as though the CLI is
always available, and a user who hits that timeout will reasonably file it as a bug.
**The README now says so** — a note at the head of "Everyday use" explains that
provisioning is Bluetooth and everything else is MQTT, that an isolated IoT VLAN can
leave a workstation with no route, and that `cannot reach broker at …:8883 (timed out)`
is that boundary rather than a fault. What is still open is the error message itself,
which reports the timeout without suggesting the likely cause.

### #70 — Write our own client identity to the robot, and drop the anonymous listener

*In progress. The decisions and their reasoning are recorded in
[design/authentication.md](design/authentication.md) — read that before changing
anything here, because several of them reverse an earlier position in this project.*

`CERT_DEVICE_CERT` (2) and `CERT_DEVICE_KEY` (3) are writable slots on the same
`mqtt-config` CERT_WRITE mechanism whiskerless already uses to install the root CA. The
robot's factory identity is therefore replaceable, not merely unreadable — we have
simply never written to those slots.

**Confirmed in the firmware, 2026-08-16, on both 1.1.65 and 1.1.75.** These are not
schema-only enum values. Inside the provisioning component — identified by its
`WIFI:PROV` log tag — six NVS keys sit in one uniform switch whose arms are 24 bytes
apart and byte-identical in shape, every one calling the same store helper:

| NVS key | `l32r` site (1.1.65) | shared call |
|---|---|---|
| `cloud_topic` | `0x400e5b2c` | `0x40145774` |
| `device_topic` | `0x400e5b45` | `0x40145774` |
| `aws_cert` | `0x400e5b5d` | `0x40145774` |
| `device_cert` | `0x400e5b75` | `0x40145774` |
| `device_key` | `0x400e5b8d` | `0x40145774` |
| `client_id` | `0x400e5bbe` | `0x40145774` |

Four of those six — the two topics, the CA and the client id — are values whiskerless
demonstrably persists on every successful re-provision, which is what makes a robot come
up on a local broker at all. That is what identifies `0x40145774` as the store path
rather than a reader. The device cert and key ride the same call, and nothing in the
switch whitelists type 1. The structure reproduces on 1.1.75 at `0x400e60ed` /
`0x6105` / `0x611d` → `0x40147684`.

Images from [huntergregal/litterrobot_firmware](https://github.com/huntergregal/litterrobot_firmware)
(`litterrobot4/ESP/`). **Still unsettled:** whether the helper commits on receipt or on
APPLY_CONFIG — that needs `0x40145774` disassembled, and radare2's Xtensa support is not
reliable enough to trust here (it decodes a known pointer table as instructions). The
enclosing function (`entry` at `0x400e586c`) has no direct callers, consistent with a
protocomm handler reached through a registration table.

#### What it would and would not buy

The firmware pins down the whole design space, so it is worth writing down what is
actually on the table before anyone spends a robot on it.

The robot's connection has three authentication surfaces, and only one is negotiable:

| surface | mechanism | status |
|---|---|---|
| robot verifies the broker | `aws_cert`, `MBEDTLS_SSL_VERIFY_REQUIRED` + `mbedtls_ssl_set_hostname` | **mandatory**, no skip path in the firmware |
| robot proves itself over TLS | `device_cert` + `device_key`, `mbedtls_ssl_conf_own_cert` | **always presented**; whether the broker *checks* it is the broker's choice |
| robot proves itself over MQTT | username / password | **does not exist** — not in the schema, the NVS keys, or the image |

So a rewrite **cannot** make the CA optional, cannot offer username/password (alone or
alongside), and cannot move the port. Those are firmware facts, not policy.

What it *would* buy is one thing, and it is a security gain rather than a simplification:
the robot's listener could stop being anonymous. With a client certificate signed by the
user's own CA, a broker can run `require_certificate true` with `use_identity_as_username
true`, authenticate each robot as a named client, and write ACLs per robot instead of per
topic pattern. The `per_listener_settings` two-listener split exists *only* because the
robot cannot authenticate, so it would collapse to one listener. It would also retire the
project's one hard requirement — that a user be able to run an anonymous listener at all.

The cost is the reversibility claim, permanently, plus an extra per-robot certificate to
issue during setup. That is *more* setup, not less. If it is ever done it belongs as
opt-in hardening for people who want it, never as the default path.

If it worked, the whole anonymous-listener requirement goes away. The robot would present
a certificate signed by the user's own CA, so the broker could run `require_certificate
true` with `use_identity_as_username true`, authenticate the robot as a named client, and
apply ACLs by identity instead of by topic pattern. That is a strictly better broker
posture than "one listener that accepts anyone".

Two reasons it has not been done, and the first is the serious one:

- **It spends the reversibility claim.** The Whisker cloud round trip works precisely
  because the factory identity is untouched: re-onboarding in the app restores stock
  operation without a single stored secret (see [recovery.md](recovery.md)). Overwrite the
  device cert and key and the robot can no longer authenticate to AWS at all — a robot
  that fails to re-onboard is a much worse outcome than a broker listener that accepts
  anonymous clients on an IoT VLAN.
- **It cannot be backed up over the air, which is byte-verified rather than assumed.**
  `mqtt-config` implements exactly six message types — CERT_WRITE, ENDPOINT_WRITE and
  APPLY_CONFIG, request and response each — and `whisker-config` six more, of which the
  only *read* returns the device id (a MAC). There is no read verb for any certificate on
  either endpoint. Since both schemas were recovered by decoding the firmware's
  protobuf-c descriptor tables, that is the complete message set, not the part we happen
  to have found. So over BLE, a half-written key or a rejected pair leaves the robot with
  no valid identity for the cloud *or* the new broker.

  **ANSWERED 2026-08-16: the app rewrites the identity on every onboarding**, so no
  backup is needed. A decoded capture of the official iOS app shows it writing all
  three certificate slots — root CA (1188 B), device certificate (1484 B) and device
  private key (1702 B) — to a robot that already had a valid identity, then applying
  and rebooting. Full record in
  [devices/litter-robot-4/provisioning/app-onboarding-capture.md](devices/litter-robot-4/provisioning/app-onboarding-capture.md).
  **Recovery from a bad identity write is therefore "re-onboard in the Whisker app",
  with no teardown and no dump.** That was the sole blocker on this item.

  **There is also a backup path, though it is no longer needed:** An `esptool read_flash` of the
  ESP32 yields the NVS partition and with it `device_cert` and `device_key` — the same
  dump already wanted for `pic_factory` (see
  [reverse-engineering.md](reverse-engineering.md), contributor path 3). It is
  non-destructive and it needs physical access to the board's UART, i.e. opening the
  robot. Anyone who dumps first can restore afterwards, which turns this entire item from
  a one-way door into an ordinary reversible change — and removes the dependency on
  whether Whisker's app rewrites the identity. **Dump first is therefore the recommended
  order for anyone attempting this**, and it is strictly better evidence than the app
  capture below, which can only ever observe one session.

**How it was settled.** The capture described above was taken and decoded on
2026-08-16; the method, the full frame sequence and the byte counts are in
[devices/litter-robot-4/provisioning/app-onboarding-capture.md](devices/litter-robot-4/provisioning/app-onboarding-capture.md).
The remaining unknown is narrow: whether the firmware commits each CERT_WRITE on
receipt or only on APPLY_CONFIG. The app stages all 46 chunks before a single apply,
which is consistent with commit-on-apply but does not prove the firmware requires it.
That only matters if someone wants a staged-but-unapplied bench probe; it does not
gate the feature, because recovery no longer depends on it.

Until then the anonymous listener stands, and [setup/mqtt-broker.md](setup/mqtt-broker.md)
says why.

### #71 — Cut an rc, then prove the certificate flow on real hardware with it

**DONE 2026-08-18, on `0.2.0-rc.32`.** Both robots are re-provisioned onto a
whiskerless-issued CA and connected to the home broker with
certificates of their own; the LR4 listener now refuses anonymous clients
(`require_certificate true`, `use_identity_as_username true`), so the broker logs
each robot by serial. What the rehearsal cost is recorded below — two bugs that
only a real robot could surface, and neither would have failed any test we had.

**Nothing in the certificate work had touched a robot before that.** It was
verified against fakes and one decoded capture, with both suites green, and the
identity write had never gone over BLE to a real LR4 — which is exactly why it
carried two defects.

**`0.2.0-rc.25` is a burned number — never reuse it.** Its first cut carried a
real robot serial in `tests/test_profiles.py`, which reached the PyPI sdist
before it was caught. PyPI has no delete API and never permits re-uploading a
version, so `whiskerless==0.2.0rc25` is permanently the contaminated artifact.

The tag was deleted, and that turned out to be the wrong move on its own:
`packaging/next-version.sh` derives the next candidate from the numeric max of
existing `v0.2.0-rc.*` tags, so deleting rc.25 made the very next dispatch
compute rc.25 *again*. That second cut was cancelled before it published
anything. **The rc.25 tag is therefore deliberately left in place with no
release attached** — it exists only so the counter advances past a number whose
PyPI slot can never be replaced. Any future forced-skip of a version needs the
same treatment: keep the tag, delete the releases.

**The rc comes first, decided 2026-08-16.** An earlier draft of this item called
the hardware test the gate *before* cutting one, which had it backwards: a
release candidate is the thing you install in order to run the test.
`prerelease.yml` says as much in its own header — tag-only, never "latest", only
offered by HACS to somebody who opted into beta. The gate it guards is the
**stable** cut, and that gate stands.

Nothing in the certificate work reaches the running Home Assistant integration,
which is what makes installing an rc on a live system safe here. Stated
precisely, because the loose version of this claim is false: the integration
imports `WhiskerlessError`, `whiskerless.safety` and the Litter-Robot 4 device
modules, and importing any of them executes `whiskerless/__init__.py`, which
does pull in `MqttSettings`. What it never does is *construct* one, open a
broker connection, or touch `profiles`, `pki` or `backup` — it rides Home
Assistant's own MQTT integration. The certificate rework lives entirely in the
CLI's path, and `grep -rn "profiles\|pki\|backup" custom_components/` returning
nothing is the check.

**State of the two robots as of 2026-08-16:** upstairs is on **Whisker's cloud**
(left there by the app-onboarding capture); downstairs is on the local broker at
your broker, provisioned by an rc build, trusting the OpenBao-backed
`LR4 Local Control Root CA`.

#### Test the identity write first — this needs no broker change at all

The point is to prove `CERT_DEVICE_CERT` / `CERT_DEVICE_KEY` actually land. Doing
that with the **existing** CA means the broker's configuration never changes and
downstairs is never at risk:

1. Export the `lr4-mqtt-ca` certificate **and key** from OpenBao to the Mac.
2. `whiskerless setup --host <your-broker-ip> --ca ca.crt --ca-key ca.key` — imports
   them, so whiskerless can now issue from the CA the broker already trusts.
3. Put **upstairs** in pairing mode and `whiskerless provision`. It is on
   Whisker's cloud, so nothing local depends on it.
4. Confirm `CERT_DEVICE_CERT` and `CERT_DEVICE_KEY` appear in the step list, then
   that upstairs shows up on the broker and
   `whiskerless state --serial <upstairs-serial>` answers. **Name the serial** —
   downstairs is the saved default and provisioning a second robot deliberately
   does not steal it, so a bare `whiskerless state` would check the wrong robot
   and pass while upstairs is unreachable.

Nothing about mosquitto changes, downstairs keeps working throughout, and the
robot now holds a certificate the broker would accept if asked.

**Do not delete the key until every robot has been re-provisioned.** Without it
`provision` leaves a robot on its factory certificate, and a listener already set
to `require_certificate true` would then refuse that robot. Finish the fleet
first, then clean up.

**And removing it takes two deletions, not one.** `setup --ca-key`
*copies* it to `~/whiskerless/ca/ca.key`, so deleting the file exported from
OpenBao leaves the signing key on the laptop. Delete both. Without the stored
copy whiskerless simply stops being able to issue, which is the state it was in
before — the CA certificate stays and robots keep working.

Only after that works is `require_certificate true` worth trying — and it needs
downstairs re-provisioned first, or it drops off.

#### Retiring OpenBao is a separate, disruptive job

The owner wants whiskerless to own the CA instead. That is a **CA rotation**, and
rotation is inherently disruptive: the moment mosquitto stops trusting the old
CA, every robot still holding it drops off. There is no ordering that avoids it —
both robots must be re-provisioned, and each is a trip to the machine.

**The directory rename makes this easy.** The store is moving from
`~/.whiskerless` to `~/whiskerless` anyway, so moving the old one aside first
means the machine simply looks new — no migration runs, `setup` offers to
generate a CA, and the whole first-run path gets exercised exactly as a new user
would meet it:

```bash
mv ~/.whiskerless ~/.whiskerless.pre-rotation    # keep it until the fleet is back
whiskerless setup                                 # asks for the broker, offers a CA
```

Migration would otherwise *prevent* this: it hoists the OpenBao certificate into
`ca/ca.crt`, and `_ensure_pki()` declines to generate whenever a CA certificate
is already on file — deliberately, because generating one over a live fleet is
what strands robots.

Nothing of value is lost. The downstairs profile holds a name and a litter
calibration, both empty on this machine, and the robot itself is untouched by any
of this — it keeps running on the old CA until the broker changes.

Then swap the cluster's mosquitto certificates for the generated ones, restart,
re-provision both robots, and only then delete the old directory.

**Decided 2026-08-16: rotate.** The signing key moves to the laptop and the
secrets manager keeps only the broker's *server* key, as transport — so
cert-manager can no longer sign that leaf, because the CA key deliberately never
reaches the cluster. That is a worse posture on paper than the arrangement it
replaces, and it is the point: it is the arrangement every user of this project
gets, and shipping a first-run path nobody has run is how the last three
"proven" claims in this repo turned out to be inherited.

`whiskerless backup` was built for this ordering — the store between generating
the CA and installing it is the only copy of a key both robots will trust. What
was actually run, 2026-08-18 (note `~/whiskerless`, not `~/.whiskerless`: the
store had already moved, so the older draft of this runbook named a path that no
longer existed):

```bash
mv ~/whiskerless ~/whiskerless.pre-rotation     # keep until BOTH robots are back
whiskerless setup --host 192.168.3.6            # offers a CA; option 1 generates
whiskerless backup ~/Desktop                     # before anything depends on it
bao kv put kvv2/k8s/bryantserver/homeassistant/mosquitto/tls ca=… crt=… key=…
#  → cluster: externalsecret-tls.yaml replaces cert-manager's Issuer+Certificate
#  → POINT OF NO RETURN: restart mosquitto; robots holding the old CA drop off
whiskerless provision --serial <each>            # once per robot, at the robot
#  → then require_certificate true + use_identity_as_username true
```

Keep `~/whiskerless.pre-rotation` until the fleet is back: it holds the old CA
certificate. The old CA's *private key* also remains in OpenBao at
`.../mosquitto/ca`, untouched — between the manifest change and the first
re-provision, reverting the manifest and restarting mosquitto is a complete
rollback that costs no bench trip.

**What the hardware found that nothing else could:**

- **The WiFi scan walked off the end of its own results.** Pages of four, and the
  last page always asked for four however few remained. This firmware answers an
  out-of-range read by dropping the BLE link — mid-provision, pairing window
  spent. A robot seeing 30 networks died on the request for 28-31. Any count not
  a multiple of four hits it, so it would have failed for most users, looking
  like flaky Bluetooth. The existing unit test *asserted* the over-read, so the
  suite was holding the bug in place.
- **The join verify threw the IP away.** The robot answers `CONNECTED` the moment
  the STA associates, before DHCP, so reading the address once always found
  `0.0.0.0`. It arrives a second or two later.

Both are fixed with regression tests. See also the `provision` UX corrections
that came out of the same session (a hint promising defaults no prompt had, the
file list printed twice, `--debug` not enabling the request log).

---

## After 0.2.0 (the durable plan)

Nothing here blocks the 0.2.0 release. Each item is deliberately *not* being
rushed into it, with the reason recorded so it is not re-litigated every cut.

**Design conversations owed, both deferred to a later version:**

- **#43 — replacing the Whisker app's notifications.** Local MQTT gives events,
  not push. Whatever we recommend becomes the answer everyone copies, so it
  wants a designed answer rather than an automation snippet dashed off.
- **#44 — could we ever offer firmware updates?** Collides head-on with the
  safety invariant: `0xA3`/`0xA4` are refused unconditionally and there is no
  override flag. The likely honest outcome is a documented *no* with the
  reasoning, which is still worth writing down properly.

**#66 — a Windows standalone binary.** Windows works today via PyPI
(`uvx --from 'whiskerless[ble]' whiskerless provision`) and `bleak` drives the built-in adapter, so
this is packaging convenience, not capability. It needs a Windows runner and a
code-signing story neither of which exists yet; until then the PyPI route is
documented in the README and is genuinely fine.

**Waiting on the world, not on us:**

- **#19** — needs Brent to answer what differs between two LR4s whose main-board
  firmware differs.
- **#21** — the state-request dropout has to recur inside a capture window
  before there is anything to look at.
- **#65** — not a task at all: HACS ships the fix or it does not. Re-check when
  they release, and change nothing here meanwhile.

**Standing activities, not release units:**

- **#15** is ongoing by design — six passes so far, each correcting the one
  before. Its *findings* ship continuously in
  `docs/devices/litter-robot-4/`; there is no version it "goes into".
- **#20** is the teardown of the capture pod, gated on #15/#16/#21 closing. It
  cannot close before the questions it exists to answer do.

---

## Added 2026-08-15

### #65 — Re-check the HACS icon once hacs/integration#5223 ships — *blocked: upstream*

The integration's own brand images work: Home Assistant 2026.3+ serves them from
`custom_components/whiskerless/brand/` at `/api/brands/integration/whiskerless/…`
and the icon renders on the integration card and its device page (verified live
on 2026.8.2, rc.21). HACS's own panel still shows *icon not available*, because
its frontend calls an outdated `brandsUrl` pointing at the public brands CDN
instead of the local proxy — [hacs/integration#5223](https://github.com/hacs/integration/issues/5223),
with [#5171](https://github.com/hacs/integration/issues/5171) as the dashboard
twin. Both were open on 2026-08-15.

Nothing to build: shipping the images inline is the current official guidance and
we already follow it. This exists so the symptom is not re-diagnosed as ours a
third time. When HACS releases the fix, confirm the icon appears in its panel and
close this. Do **not** work around it by adding the integration to
`home-assistant/brands` — that repository stopped accepting custom integrations
at HA 2026.3.

---

## Done (archive)

- #63 provision collects the username: **done 2026-08-15** — an optional prompt, offered from what the saved robots agree on, `-` to decline an inherited one, and skipped entirely when stdin is not a TTY so a fully-flagged run never hangs on an optional question. The password stays per-run and unwritten
- #64 BLE error translation: **done 2026-08-15** — `scan`, `read_device_mac` and `provision_robot` wrap bleak at the boundary and raise `ProvisioningError` naming what was being attempted ("BLE scan failed: Bluetooth device is turned off"). The CLI cannot catch `BleakError` itself: bleak is the optional `[ble]` extra
- #55 CLI equivalence: **done 2026-08-15** — `status` renders the derived view from one FRESH document plus stored calibration (draining anything queued first, since `calibrate` runs seconds after someone changed the globe), `panel-reset` presses Reset, and `calibrate full|empty` persists a manual reference in the profile store. One rule judges a calibration pair and both commands consult it: `calibrate` will not write a pair that cannot be a scale, `status` will not present or use one, and a stored pair that is already broken is cleared rather than allowed to veto its own repair. The 24/7-derived facts stay HA-only by design, and `status` says so rather than printing zeros
- #54 derive.py: **done 2026-08-15** — `src/whiskerless/devices/litter_robot_4/derive.py` owns every derived fact as a pure reducer `(DerivedState, message, now) -> (state, changed, effects)`; the coordinator stores what the effects tell it to and the entities only read, the binary sensors' merge policies (globe-fault OR, excess-weight threshold, hopper-empty floor) moved with it, the dedupe windows are one wall clock (which also fixed the first reading after every boot being discarded), and five per-capability bootstrap blobs became one derived snapshot (a blob without a gauge could clobber the persisted one)
- #49 sighting evidence: **done 2026-08-15 with #54** — each sighting records WHAT proved it (`Evidence`), and `ACCEPTED_EVIDENCE` per capability decides what a rule change retires; the global revision counter is gone, its marker pinned at 3 only so a downgrade does not re-run the old sweep. Unrecognized kinds are trusted (a newer build wrote them), unlabelled ones are re-examined once where the old sweeps never validated them
- #56 beam gate: **done 2026-08-15 with #54** — the visit-close window is now the 90 s grace PLUS the duration the close claims, since the break that stamps a visit lands at its start and state documents arrive minutes apart. RESIDUAL: a visit that produces no state document at all (a settings write holds the lock through it) still has nothing to stamp; activity `0x37` was rejected as the stamp because its bit 0 stayed set through a 2h15m bit-1-only run, so it is not the ToF sight line
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
