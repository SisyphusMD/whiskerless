# Backlog

The project's working task list. Numbering is historical (it began life in a
working session's task tracker) and is kept stable because commits, docs and
review notes cite these numbers — do not renumber. New tasks append at the end.

Statuses: **open** (nothing started), **blocked** (says on what), **discuss**
(needs a design conversation before any code).

## What is actually left — as of 2026-08-19

Items live in dated sections and keep their place when they finish, so the reasoning
stays where it was written. That makes status unreadable by scrolling, hence this
list. **Each item's own heading is the source of truth; this is a pointer.** Update
it in the same edit that changes a heading — #64 and #69 both sat finished with no
marker, and #64 read as open for four days after it shipped.

**Ready to work on:**

- ~~**#79**~~ — closed: decoded, the CLI qualifies the drawer line, and the HA sensor
  keeps its value while carrying a `level_provisional` attribute.
- **#68** — the hopper gauge under-reports.
- ~~**#83**~~ — closed: `diagnose` is gone, and its library functions with it.
- ~~**#84**~~ — closed: the false "only advertises while you hold" instruction is gone
  from every place it was said.
- ~~**#85**~~ / ~~**#86**~~ — closed: the picker, the announcements, `rename`, and
  `--serial` taking a name all landed together.
- **#88** — sweep the command surface, verified from telemetry rather than by eye.
- ~~**#21**~~ — answered: the robot's own MQTT client wedges — two TLS handshakes abort and it
  stops retrying, while staying pingable. Not WiFi coverage and not an integration fault;
  `wifiRssi` looked implicated and was not. Recovery is a power cycle.
- ~~**#87**~~ — closed: the README prose is impersonal in both repos (whiskerless 13 hits to 3,
  dreame to 0). The three survivors are quoted CLI menu labels in the USER's voice and one passage
  quoting them, all kept on purpose.
- **#82** — hidden-SSID joining is asserted in a comment and has never been tested on
  hardware.
- **#81** — "Replace Filter" is the only Whisker-app control with no equivalent here,
  and whether it is even remotely reachable is unresolved.
- ~~**#51**~~ — closed: the firmware's own descriptor tables enumerate every message
  type and none is a read.
- **#15** / **#20** — the rolling capture: keep analysing, and retire the pod when
  the questions close.
- **#45** — its heading says DONE and the sleep flag half is, but `0x4C` is still
  unanswered under that number, and the awake-deferral test that would discriminate
  it has not been run. Listed here because the heading alone hides it.

- ~~**#80**~~ — solved: pairing mode holds the WiFi station down and never ends by
  itself; only a completed provision restores it.

**Design conversations, not code yet:** #43 (replacing the app's notifications),
#44 (firmware updates, which collide with a safety invariant), #89 (provisioning from Home
Assistant over its own Bluetooth stack, with an external issuer so the CA signing key stays out of HA),
#90 (telling a robot that has left the broker apart from one that is merely not answering).

**Waiting on something outside the repo:** #13 (empty half — costs a litter refill)
and #14 (the same press), #19 (Brent), #22 (the
sleep/wake *write* path is still untested live, though its original premise is void),
#23 (a narrated visit), #65 (upstream HACS).

**Nothing here gates the 0.2.0 release.** #71 was the last one and closed
2026-08-19.

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

So each release now ships **`SHA256SUMS-x86_64`** and **`SHA256SUMS-aarch64`**
covering the Linux artifacts, which closes the real gap ("did this arrive
intact") with no key to hold, rotate or revoke. One file per architecture because
each is written by the forge that built those bytes and published assets are
immutable; they are named for `uname -m` so `sha256sum -c --ignore-missing
SHA256SUMS-$(uname -m)` needs no editing. Their limit is stated in the workflow:
served from the same host as the artifacts, they prove integrity and not
authenticity.

**Then the condition it named came true.** The repositories in #77 are exactly
the "something verifies it automatically" case, so the packages are now signed
with `CCE50015D058E9BF` as well. On dnf that signature is what `gpgcheck` checks
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

(`nas-pkg` is now `nas-bridge`: once arm64 moved to a native GitHub runner it had
more than the `.pkg` to carry.)

### #74 — Forgejo has no infra-retry, and no rerun API to fall back on — **CLOSED 2026-08-19: recovery shipped, and the rest rested on a misdiagnosis**

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
job fails the cut and needs a manual re-dispatch.

**Resolved 2026-08-19 — by building the retry, not by arguing it was impossible.**

*Automatic, in-step.* Every `actions/setup-python` in `.forgejo/workflows` (15 of
them, across ci/prerelease/publish/release/tap-bottles) now runs twice: the first
attempt carries `continue-on-error: true`, and a second, identically configured
attempt is guarded by `if: steps.<id>.outcome != 'success'`. That needs no rerun
API, and it addresses the recorded failure directly — all five jobs died *in*
setup-python, which is precisely where this now recovers.

The guard is deliberately `!= 'success'` and not `== 'failure'`. With equality, a
runner that left `outcome` unset would skip the retry *while* `continue-on-error`
had already swallowed the first failure — so the job would carry on against
whatever interpreter happened to be on the image, and could pass at the wrong
version. Inequality retries on anything that is not a clean success, and a failed
retry fails the job.

**An earlier draft of this closure claimed automatic retry "cannot be built"
because Forgejo has no rerun endpoint. That was wrong**, and wrong in a way worth
naming: no-workflow-rerun-API does not imply no-retry. The retry belongs in the
step, not the workflow.

*Manual, whole-workflow.* `ci.yml` also has `workflow_dispatch`, which remains the
fallback when a job fails somewhere the in-step retry does not cover.

**The retry has never fired, and cannot be made to on demand** — a transient
manifest outage is not reproducible, so what is verified is the wiring, not the
recovery: all 15 pairs parse, ids are unique per job, each guard names its own
first attempt, and the two `with:` blocks are identical. First real transient fetch
failure is the test; note here whether the second attempt rescued it.

**On the cause, kept hypothetical.** The household internet was intermittently
down across that window and the same period produced a second network-shaped
failure, but neither was traced to it — and because all five jobs stopped at
setup-python, no run evidence exists about whether `pip`, apt, dnf or Homebrew
would also have failed. Do not restate the outage as established fact.

Worth knowing for whoever revisits this: **there is no PyPI mirror**, so every
job's `pip install` reaches the internet, and the install matrix additionally pulls
from apt, dnf and Homebrew. A pull-through cache on the NAS alongside the existing
container mirror would narrow that surface — but it is a CI-speed and
supply-chain-control argument, it would not make a build survive a full outage on
its own, and it is a separate item, not this one.

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

LEAD, tested negatively (2026-08-19): `0x5F`-`0x63` fire only in the same second
as a globe-motor fault raise, twice in five days, values `55/12`, `14/14`,
`326/172`, `65520` (`0xFFF0` = -16 int16) and `0/0`. A further 3d22h carried no
`0x35` and none of the five — which is what the reading predicts and is the
cleanest test it has had, but still leaves two samples from one fault on one
robot. Next fault is still the decode.

SEVENTH PASS 2026-08-24 covered 5d07h (08-19 21:11Z → 08-25 04:52Z) from Loki:
1,065,899 lines → 47,655 records, 0 malformed → 17,359 readings across 7,322
distinct payload seconds, deduped on (payload time, SERIAL, register, value) — the
serial belongs in the key for any pass spanning both robots, or two devices
reporting one value in one second collapse and a board looks exclusive when it is not (the mbRevision 89 board 13,973; the mbRevision 93 board 3,386).

**The lead had its cleanest test yet and survived without advancing.** Zero
`0x5F`-`0x63` in 5d07h, and zero `0x35` — which is the evidence that matters,
because `0x35` is the fault marker the reading is coupled to. The state fields are
NOT usable as proof here: `events.py` records a captured live fault during which
`globeMotorFaultStatus` stayed zero throughout, so their being zero across this
window (they were) says nothing either way. On the `0x35` evidence this window is
fault-free, which makes it consistent with the reading rather than support for it —
a fault WITHOUT the five is what would refute it, and none occurred. Cumulative
clean run is now 3d22h + 5d07h ≈ 9d05h. Still two samples from one fault on one
robot. Next fault is still the decode.

**RETRIEVAL, corrected again.** `kubectl logs --since-time` returned 549 lines
covering five MINUTES: the container log had rotated, even though the pod itself
has 1 restart and 5d23h uptime. The rule above ("while the pod is alive with 0
restarts, kubectl beats Loki") needs a third condition — the container log must
not have rotated past the window. Check what `kubectl logs` actually spans before
trusting it; Loki held the full 5d07h.

**`registers.md` is one register behind the decoder, not four.** A first pass
here claimed `0x3E`, `0x49` and `0x59` were undocumented; they are not. The file
covers them as RANGES — `0x3D–0x40` for the odometers, `0x48`–`0x4A` for the three
drawer lasers, `0x58–0x5A` for ToF1/2/3 — which a literal search for `0x3E` misses.
Only `0x0C` (`LITTER_HOPPER_DISPENSED`, named in `events.py`) is genuinely absent.
Search that file for ranges before concluding anything is missing from it.

**`0x3E` corroborates its own decode**, independently of the code: 155 readings,
155 DISTINCT values, and consecutive where they cluster (`0x1FC5`, `0x1FC6`,
`0x1FC7`, `0x1FC8`, `0x1FC9`, `0x1FCA`). A monotonic counter that never repeats a
value is what `ODOMETER_CLEAN_CYCLES` should look like.

**RETRACTED, and replaced by a better result: there is no gap.** This entry first claimed
`0x6D` emits from inside the sweep's only silent gap. An active sweep of the OTHER robot
(2026-08-25, `0x00`–`0x7F`, paced 3s) then showed `0x6A`–`0x6E` answering there, and repeat
probes showed them answering on the swept robot too — the addresses `registers.md` records as
"the only gap inside the low range". Two passes on each robot, every one of the five returning
`0x0000`. **The documented gap does not reproduce.**

What silence actually does is MOVE. The upstairs sweep found exactly one silent address
(`0x73`), which then answered 231 on three consecutive confirmation passes. Downstairs, `0x73`
was silent once and `0x6A` was silent once, both answering on the next pass. A read that
succeeds takes 0.3-0.5s, measured across seven registers, so these are not slow answers inside
an 8s budget. What causes them is NOT established: 24 consecutive reads of `0x34` dropped none,
but at roughly one miss per 128-read sweep that run is what uniform loss would also produce, so
it distinguishes nothing. Occasional, and cause unknown.

This is the direct evidence for the warning `registers.md` already carries — "a silent register
proves nothing on its own" — and it is worth more than the finding it replaces. A single-pass
sweep manufactures phantom gaps, and one of them had been written down as fact until this pass
retracted it in `registers.md`.

The rest, classified against what that file actually says rather than a literal search for each
address (three separate claims in this pass were wrong because ranges do not match a text
search for `0x3E`):

| Register | Status in `registers.md` | Readings | Values | Seen on |
|---|---|---:|---|---|
| `0x6D` | answers a read on BOTH robots (the "gap" is retracted above) | 6 | `0x0101`, `0x4101`, `0x8101`, `0x8100`, `0x4100`, `0x0100` | rev 89 |
| `0x65` | answered the sweep, named nowhere | 25 | always `0x0000` | both |
| `0x67` | answered the sweep, named nowhere | 45 | 29 distinct (`0x011B`, `0x0119`, `0x020F`, `0x0319`) | rev 93 |
| `0x71` | answered the sweep, named nowhere | 4 | always `0x0001` | rev 89 |
| `0x74` | listed "answering but unidentified" | 4 | `0x00FB`, `0x01EC`, `0x022B`, `0x03F2` | rev 93 this window |
| `0x75` | listed "answering but unidentified" | 1 | `0x00E4` | rev 93 this window |

`0x74`/`0x75` sit inside `0x73`–`0x7F`, which that file calls a board identity block
(`0x79` = `mbRevisionId`, `0x7A` = `mbDeviceId`, `0x7F` = `mbHardware`). Both firing in one
second is what a board-identity read looks like, which is why they are kept OUT of the
firmware correlation below rather than counted toward it.

**The per-robot split tracks MAIN-BOARD firmware, and that is the strongest
result in this pass.** Equal `espFirmware=1.1.75` rules out only an ESP-build
difference — #19 said as much and kept a firmware explanation open. The main board
is where they differ, on identical hardware (`mbHardware=10500`, `mbBom=3072`,
`mbSuite=2`, same `mbDeviceId` on both):

| `mbRevision` | `mbBuild` | `mbRevisionId` | emits |
|---:|---:|---:|---|
| 89 | 1 | 41027 | `0x6D`, `0x71` |
| 93 | 2 | 41088 | `0x67` |

`0x74`/`0x75` are deliberately NOT in that table. The sixth pass saw `0x74` from BOTH
robots in boot windows, so its one-sided showing here is this window's sample, not a
board-linked trait, and it cannot support the correlation.

Identified by board revision rather than by "robot 1/2": that numbering is already in
use elsewhere in this file and mapping onto it was not verified here.

The newer board emits one set and the older the other, with `0x65` on both. That is
a clean correlation on n=2 rather than a proof, and the test is cheap: when either
board updates, its unknown registers should switch sets. **Do NOT attribute this to
accessories** — both robots carry a LitterHopper (see the 08-11 night), so the
`0x0C` count difference is usage, not inventory. `0x74`+`0x75` landing in one second
still reads as a one-off report dump rather than telemetry.

Rolling LR4 capture analysis (pod `lr4-capture` in namespace `homeassistant`).

Sixth pass 2026-08-19 covered 3d22h (08-15 18:46Z → 08-19 20:42Z) from Loki:
392,050 lines → 17,143 records, 0 malformed → 5,415 deduped readings, state and
command continuous. Fifth pass 2026-08-15 covered the whole 5d04h (08-10 14:18Z →
08-15 18:46Z), 535,778 lines, 1 malformed. Fourth pass 2026-08-10/11 covered
12h19m (14:18Z–02:37Z), 1346 records, 1346/1346 JSON, 0 orphans, 0 restarts.

RETRIEVAL, corrected: the k8s-workerbig reboot on 2026-08-15 00:31Z made the
Deployment replace the capture pod, and the old pod object was deleted with its
log directory — so `kubectl logs` offers 17 hours and nothing earlier. (For an
ordinary container restart inside a surviving pod, `--previous` is still the
cheaper answer; this was not that.) LOKI HAS THE REST, earlier pods included — the working note saying Loki was
unusable here is wrong. Query `{namespace="homeassistant", pod=~"lr4-capture.*"}`
and page it forward (limit 5000, cursor past the newest line of each batch).

METHOD RULE, learned the hard way: time everything by the payload's own
`timestamp` and dedupe on (payload time, SERIAL, register, value). The serial is
part of the key, not optional: a pass spanning both robots that omits it collapses
two devices reporting one value in one second into a single reading, undercounting
a board and able to manufacture the appearance that a register is exclusive to one. Passes 1–3 used MQTT
arrival stamps, which shifted cycle boundaries by seconds, inflated every
activity count and hid that `-30` fired twice in one cycle.

SECOND METHOD RULE (2026-08-19): collapsing a second into
`{register: value}` drops readings, because a register can emit several distinct
values in one second — `0x4F` does it in 182 of 489 seconds, `0x34` in 69 of 335,
`0x37` in 34 of 870, `0x01` in 4 of 25. Keep `{register: [values]}`. The
pairing registers are unaffected (`0x3C`, `0x66`, `0x5E`, `0x64`, `0xB9`, `0xBC`,
`0x33`: zero lossy seconds each).

While the pod is alive with 0 restarts, `kubectl logs --timestamps --since=Nh`
beats the Loki export outright. Use Loki only across a restart or past the
container log.

Each pass has corrected the one before it — treat every conclusion as
provisional. The sixth pass moved four of these: `0x66` is `0x3C` at 16×
resolution with a movement-dependent sampling skew; `0x33` is constant at `34` on
both robots; `0x5E` and `0x64` never co-occur and alternate by cycle position;
`0x3402C0` reproduced at 5× the data as the clean-delay tick with bursts of 1-15.
The `0x10`/`0x20` line below was stale rather than open — `registers.md` has had
`0x37` as PROVEN (`catDetect`, bit 1 = load cell) since the narrated session, and
four more days agree with it; the one value it does not cover is `0x1021` ×7. Still uninterpreted: `0x49`, `0x4A`, what
`0x3C`/`0x66` physically measure, why the pre-cycle marker alternates `0x10xx` vs
`0xE065`, `0x37` = `0x1021`, `0x01` `0x1002` (a hold of an unnamed button), and
`0xBC` = 15699. `0x33` is not uninterpreted so much as untestable passively.
Above `0x7F` remains robot-2-only across nine days.

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
(#16 hopper flap, #15 more clean cycles for `0x3C`/`0x66`). It earned its keep on
2026-08-28: the capture is what answered #21.

Loki retention is 720h (30 days), so the useful window is a rolling month —
findings must be written into `docs/devices/litter-robot-4/capture-notebook.md`
as they are found, not left to be re-derived from logs that will age out.

It is a diagnostic, not permanent: it holds an extra port open on the mosquitto
Service and a CiliumNetworkPolicy pair in the homeassistant namespace. When
#15/#16/#21 close, delete `apps/homeassistant/app/lr4-capture` and revert the
additive mosquitto Service port and ingress rule.

### #21 — Investigate the recurring "did not respond to a state request" dropout — **ANSWERED 2026-08-28: the robot's MQTT client wedges; the network is fine**

Negative result 2026-08-10 over a clean 8h25m window (one pod, 0 restarts): 277
state requests (`0x02A00000`), 277 answered within 30s. Reply latency median
2.0s, p90 5.0s, max 11.0s. Zero gaps over 6 minutes between consecutive state
messages; the largest gap was 303s, which is the 5-minute heartbeat itself.

The dropout does not reproduce under ordinary conditions and is not a steady
background rate. Next time it fires, grab the wall-clock time and correlate
against the capture rather than trying to provoke it.

**It fired 2026-08-28.** The downstairs robot stopped publishing at 11:32:10Z (04:32 local).
The broker log — timestamps below in **local time**, which is what mosquitto records — says
exactly what happened:

    04:33:47  Client <serial> has exceeded timeout, disconnecting.
    04:34:34  New connection from <robot>:58089 on port 8883
    04:34:34  OpenSSL Error[0]: error:0A000126:SSL routines::unexpected eof while reading
    04:34:34  Client <unknown> disconnected: Protocol error.
    04:36:42  New connection from <robot>:58090 on port 8883
    04:36:42  OpenSSL Error[0]: ...unexpected eof while reading
              (no further connection attempt for the next ten hours)

Mosquitto dropped the session on keepalive timeout, the robot retried twice, both retries
aborted **mid-TLS-handshake**, and its client then stopped trying altogether. Throughout, the
robot answered ICMP with 0% loss: powered, associated, routable, and reachable. Only its MQTT
client was dead. A config-entry reload does not help — the robot never reaches the broker.
Recovery is a power cycle of the robot.

It is robot-side, not broker-side: the other robot completed a TLS handshake against the same
broker three hours later and kept cycling normally, and the broker certificate is valid into
2036 and was not rotated that day. Both robots reconnect on a ~15-20 minute cycle as a matter
of course (27 and 10 times respectively over the day), always logged as "already connected,
closing old connection" — the firmware opens a new session without closing the old one. That
is normal for these units; what is not normal is a handshake that aborts and a client that
then gives up permanently.

**`wifiRssi` did not explain this incident, and reading it as though it did cost this entry a
wrong answer for several hours.** The value is bimodal on *both* robots — two tight clusters
about 20 dB apart with nothing between them (downstairs ~-64 / ~-84, upstairs ~-49 / ~-72) —
and the cluster changes when the robot reopens its MQTT session. That is consistent with the
robot resampling on reconnect, and with two access points; it is not by itself evidence that
the field is wrong, and the `0xA1` protocol notes and the shipped signal sensor both treat it
as real. What it is *not* is a diagnosis. Two tests rule it out as the cause here:
inter-message cadence is identical in both clusters (median 3.0s, max ~302s in each), so the
link carried traffic equally well at either number, and the robot with the worse numbers is
not the one that drops out more often.

The lesson for the next reader is narrower than "ignore this field": a low RSSI is a
correlation, and the cluster structure means a single sample says less than it appears to.
Establish whether the link is actually degrading — cadence, loss, retries — before concluding
from the number alone.

So the dropout is a firmware fault in the robot's network stack, not a WiFi coverage problem
and not an integration defect. The integration behaves correctly throughout: it stays loaded
and subscribed (no `SETUP_RETRY` in a full day of logs), retries on its heartbeat, and
`_handle_message` restores availability on the first pushed state.

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

### #51 — Probe whether mqtt-config / whisker-config expose a READ for certs and endpoints — **CLOSED 2026-08-19: no read verb exists, and the firmware itself says so**

The mapped provisioning message set is write-only for config; the single
exception is `whisker_device_id_request`, which proves the whisker-config
endpoint answers reads. A GET for the root CA, host or topic endpoints may
exist unmapped — we inferred write-only from what we implemented, which is not
the same as the firmware not offering it. Probe the message-type space on both
endpoints against a robot in pairing mode (read-only, no writes). A read would
make a pre-provisioning snapshot possible and would reveal Whisker's own AWS
endpoint hostname — the one value blocking a self-contained
`whiskerless restore-cloud` that does not depend on the Whisker app.

**Answered without needing the bench at all — the enums were already in this repo.**
`provisioning/whisker_mqtt_config.proto` and `whisker_config.proto` carry every
message type, and their provenance note is the point: each enum value was
"byte-verified by decoding the protobuf-c ... EnumDescriptor tables in the firmware
image", so the lists are complete by construction rather than by observation.

| endpoint | request types the firmware declares |
|---|---|
| `mqtt-config` | `CERT_WRITE_REQUEST` 0, `ENDPOINT_WRITE_REQUEST` 2, `APPLY_CONFIG_REQUEST` 4 |
| `whisker-config` | `DEVICE_ID_REQUEST` 1, `DEVICE_REBOOT_REQUEST` 3, `DEVICE_ID_SET_REQUEST` 5 |

Every other value is the paired `*_RESPONSE`. **No read exists for a certificate,
an endpoint or the host**; the single read on either endpoint is
`DEVICE_ID_REQUEST`, and it returns the 6-byte MAC. So the pre-provisioning
snapshot this task hoped for is not possible, and Whisker's own AWS endpoint
hostname cannot be recovered from the robot — `restore-cloud` stays dependent on
the Whisker app. That is a firmware fact, not a gap in our mapping.

**The bench work was unnecessary, and that is the lesson worth keeping.** Two
pairing windows were spent probing a message space the repo had already enumerated
from the firmware image. Read `provisioning/*.proto` before designing an
experiment against these endpoints.

Two incidental results, since the runs happened anyway:

- **Releasing the Connect button does NOT drop an established BLE link** —
  controlled directly: a known-good read passed, the operator released, and the
  same read passed again twelve seconds later. Worth knowing, because it means the
  hold is needed only until the link is open.
- **`whisker-config` msg=0 (`UNKNOWN_CONFIG_TYPE`) drops the link**, with that same
  read passing immediately before it and failing immediately after. Note this is
  the enum's own "unknown" sentinel rather than an unmapped number. An earlier run
  saw msg=2 (`DEVICE_ID_RESPONSE` — a *response* type sent as a request) do the
  same, but that run had no release control, so treat it as suggestive only.

An earlier draft of this entry called those values "unrecognised message types" and
extrapolated a 25-pairing-window sweep from them. Both are wrong: the values are
declared enum members, and no sweep is needed because the enums are already known.

### #52 — Use the device-id read to verify (or supply) the serial — **CLOSED 2026-08-16: answered, not viable**

**Answered 2026-08-16: the read returns a MAC** (`b4:8a:0a:xx:xx:xx`), not the
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

### #63 — provision should collect (and store) the broker username — **CLOSED: overtaken, cannot be done**

0.2.0 removed broker usernames and passwords from the project entirely — the
robot cannot send credentials at all, so running two authentication schemes
against one broker bought nothing (see [design/authentication.md](design/authentication.md)).
There is no `username` profile field, no `--username`, and `MqttSettings` carries
no credentials. The premise below is false as of 0.2.0 and is kept only to say so.

*Original, no longer achievable:* `username` is a stored profile field, but provision never asks for it — on an
authenticated broker the advertised bare commands fail until the user passes
`--username` every time or hand-edits `profile.json`. Prompt for it (optional,
enter-to-skip) during provisioning, offer the value the saved robots share the
way host/CA/SSID are offered, and keep the password per-run as designed.

### #64 — translate BLE-stack errors at the library boundary — **DONE 2026-08-15**

**This heading carried no status until 2026-08-19 while the archive below already
recorded it as done, so the item read as open for four days.** The work is in
`ble/transport.py`, which catches `bleak.exc.BleakError` at the boundary and raises
`ProvisioningError` naming what was being attempted.

The original statement, for the reasoning: `BleakError` escaped to the CLI raw, so a
Bluetooth failure during provisioning ended in a traceback. The CLI cannot catch it
by type — `bleak` is the optional `[ble]` extra and must not be imported
unconditionally — so the wrap has to happen inside `ble/`, exactly as the MQTT link
wraps its connect errors.

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

### #69 — The CLI assumes the operator's machine can reach the broker — **DONE** (docs 2026-08-16, error message shipped, confirmed 2026-08-19)

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
is that boundary rather than a fault. The error message was the last open half, and it
has shipped too: `link.py` appends "Nothing may be wrong: provisioning is
Bluetooth, but this command needs a network route to the broker, and an isolated
IoT VLAN usually denies one from a workstation" whenever the failure is a timeout.
Seen in the wild 2026-08-19, which is what closed this.

That workstation's route was separately fixed in the cluster the same day — the
broker's pod attaches only to the IoT VLAN and so could not answer a host on
another subnet — but that is this owner's network, not a property of the tool, and
it is why the message stays.

### #70 — Write our own client identity to the robot, and drop the anonymous listener — **DONE 2026-08-18**

**Both robots hold certificates issued by our CA (CN = serial), and the listener
no longer accepts anonymous clients.** `require_certificate true` +
`use_identity_as_username true`, so the broker logs each robot by serial rather
than a self-chosen client id, and a client presenting no certificate is refused
(verified directly). The diagnostic subscriber needed an identity of its own —
anything else still using that listener stops the moment it is tightened, which
is now written up in [setup/mqtt-broker.md](setup/mqtt-broker.md).

*The decisions and their reasoning are recorded in
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

### #71 — Cut an rc, then prove the certificate flow on real hardware with it — **DONE 2026-08-19 on `v0.2.0-rc.34`**

**Done, and with the artifact this time.** Both robots — **both on ESP 1.1.75**, so
this validates that firmware and says nothing about 1.4.4 — were re-provisioned from
the published **Homebrew bottle** (`poured_from_bottle: True`, arm64; an editable
install from `src/` would have passed the same commands while proving nothing about
what users get).

**Two separate claims, proved by two different things — do not merge them.**

1. *The packaged artifact exercised the write path.* Proof: the robot's own
   acknowledgements over BLE — `CERT_DEVICE_CERT` (1066 B), `CERT_DEVICE_KEY`
   (1675 B), `APPLY_CONFIG committed`, `DEVICE_REBOOT` — and the stored files match
   those byte counts.
2. *The broker accepts the robot on a certificate.* Proof: it reconnected and
   mosquitto logged the certificate CN as the username, which is what
   `use_identity_as_username true` does on a listener running
   `require_certificate true`.

**The username alone does NOT prove the new certificate landed.** Both robots
already held `CN=<serial>` certificates from the 2026-08-18 source run, so that log
line would look identical if the BLE write had silently failed and the robot kept
its old identity. Distinguishing them needs the presented certificate matched by
fingerprint or serial, which mosquitto is not configured to log. The write is
evidenced by claim 1, not claim 2.

The store upgraded itself in the same runs: `robots/<serial>/client/` now exists for
both (neither had a stored identity — they predate per-robot storage), and
`broker.json` gained `"auth": "mutual"`.

The earlier 2026-08-18 run is what this item existed to reject: it re-provisioned
both robots successfully, but with `.venv/bin/whiskerless`, which proves the code
and not the artifact — the inherited-confidence failure this repo keeps having.
`0.2.0-rc.32`'s artifact could not provision at all (its WiFi scan dropped the BLE
link), which is precisely why "it works from source" was not good enough.

**The run found two defects nothing else would have** — both fixed in `9c429c1`:
the hold hint told people to wait for a beep the LR4 cannot make (while this same
command's failure path already said BLINKS YELLOW), and the lease guard excluded
only `0.0.0.0`, so a robot answering `1.0.0.0` printed an address it did not hold
*and* ended the wait that would have collected the real one. See #79 for the third
thing the night turned up.

**Nothing in the certificate work had touched a robot before the 2026-08-18 source
run** — that run, not the rc.34 one above, was the first time any of it met
hardware. It was
verified against fakes and one decoded capture, with both suites green, and the
identity write had never gone over BLE to a real LR4 — which is exactly why it
carried two defects.

**`0.2.0-rc.25` is a burned number — never reuse it.** Its first cut carried a
real robot serial in `tests/test_robot_profiles.py`, which reached the PyPI sdist
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

#### HISTORICAL — the pre-test procedure, kept for its reasoning only

**Do not follow the steps below.** They are the plan as it stood before any of this
ran, and every premise has since changed: both robots are re-provisioned onto the
whiskerless CA, the listener already enforces `require_certificate true`, and
upstairs is not on Whisker's cloud. What is still worth reading is *why* the plan
was staged the way it was — test the identity write against the existing CA first,
so the broker's configuration never changes and the other robot is never at risk.

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

**Do not delete the key until every robot has been re-provisioned.** Since 0.2.0 a
store that cannot sign is refused before a robot is touched, so deleting it leaves
a store that cannot provision at all. Finish the fleet first, then clean up.

**And removing it takes two deletions, not one.** `setup --ca-key`
*copies* it to `~/whiskerless/ca/ca.key`, so deleting the file exported from
OpenBao leaves the signing key on the laptop. Delete both. Robots already
provisioned keep working; adding one means importing the key again.

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

## Added 2026-08-19 (from the bench night)

### #79 — Decode `isDFIResetPending` and stop presenting a provisional drawer level as measured — **DONE 2026-08-19**

`IS_DFI_RESET_PENDING = 0x41` had a constant in `const.py` and was decoded **nowhere**
— not in `models.py`, not in the CLI, not in the integration. The firmware sets it
the instant a Reset press zeroes the drawer gauge, and clears it when the next cycle's
lasers actually measure. So between those two events the robot is telling us in as
many words that the number it is reporting is unconfirmed, and we throw that away and
publish the number.

Observed live 2026-08-19 (1.1.75): Reset at 01:23:43Z zeroed the gauge and raised
`0x41`; the cycle measured at 01:28:44Z and cleared it. For those five minutes
`whiskerless status` printed `waste drawer 0%` / `drawer full False`, and the HA
`waste_drawer_level` sensor published `0`, with nothing marking either as a guess.
**Both halves are now fixed.**

**Do not justify this with "the 0% was wrong".** That reading was made and corrected
on the night: the 14 % measured afterwards is explained by cat waste the globe dumped
into the freshly lined drawer during that same cycle, so the drawer had genuinely
changed and the zero may well have been right when written. Whether Reset's optimistic
zero is ACCURATE is untested and needs a Reset on an empty drawer with an empty globe.
The defect is that we present an explicitly-unconfirmed value as a measurement,
regardless of how often it happens to be correct.

This is not hypothetical exposure: `docs/setup/home-assistant.md` actively recommends
alerting on *Waste drawer level* crossing a threshold, which is exactly the automation
a provisional value can mislead.

**Decode: DONE 2026-08-19.** `LitterRobot4State.is_dfi_reset_pending` carries the
flag, and `whiskerless status` qualifies the drawer line with "not measured yet —
reset, awaiting the next cycle" rather than printing a bare percentage. Absent is
treated as not-pending, so a firmware that never sends the field is unaffected.

**Home Assistant: DONE.** The owner chose the conservative option — the sensor keeps
publishing the value, so nothing keyed on it breaks, and carries a
`level_provisional` attribute. Absent flag means no attribute at all: `False` there
would assert "measured" about a robot that never said so. An HA sensor going `unknown` while pending is one option and would break
any automation keyed on the drawer reaching zero; an attribute plus a documented
caveat is the conservative one. Whichever way, `docs/devices/litter-robot-4/registers.md`
now carries the `0x41` row, so the wire meaning is settled and only the presentation
is open.

---

## Added 2026-08-19 (from the bench night, second half)

### #80 — **SOLVED 2026-08-19:** pairing mode takes the robot OFF WIFI, and never ends on its own

**Owner-reported as recurring, timestamps captured 2026-08-19.** Robot 2 (upstairs)
stopped publishing and never came back on its own; a re-provision is the only known
cure and works every time.

**Mechanism, established by measurement.** Pairing mode holds the WiFi station in
`CONNECTING` and it never completes, so the robot is off the air for as long as the
mode lasts — and the mode **never times out** on this firmware. The only thing that
ends it is a completed provision, which is why a re-provision cures this every time:
it finishes provisioning and reboots.

The decisive evidence is a ping from the robot's OWN VLAN, which removes the
cross-subnet and power-save excuses that made earlier ping results worthless:

```
from br3 (192.168.3.1, on the IoT VLAN):
  robot 2 (stranded)   100% loss, ARP INCOMPLETE   <- not associated at all
  robot 1 (control)    0% loss, 84 ms              <- healthy; 84 ms is power-save
```

`INCOMPLETE` means the gateway cannot even resolve its MAC. It is not "connected but
unreachable" — the station is down. A BLE read of the stock `prov-config` GetStatus
in the same state agrees: `state=CONNECTING` on 8 of 8 polls over 25 s, with no
`fail_reason` and no address. That reading was initially discarded as confounded by
pairing mode; once pairing mode turned out to BE the fault, it became the direct
observation of it.

**Whisker documents this themselves, and it goes further than our measurement.**
<https://www.litter-robot.com/support/article/litter-robot-4-not-connecting/>: "If
the Connect button is held too long and the Connect light starts blinking yellow, the
robot has entered onboarding mode **and forgotten its saved WiFi network**." That is
the missing half — the station is not merely held down, the credentials are gone, so
there is nothing to reconnect to and only a completed provision restores it. Their
recovery is the app's "Update Network" flow, which is what `whiskerless provision` is.

**Whisker's own support pages say a press-and-release of Connect exits onboarding
mode. On this hardware it does not** — it toggles the WiFi radio, observed three
times out of three on 2026-08-19 (white light bar = radio off, a second press
restores it). A Connect *hold* while already in pairing mode just re-arms pairing.
There is no button that leaves the mode.

**This is NOT local-broker-specific, and the owner's contrary impression is
explained.** The Whisker page above is written for stock cloud users — it is their
common failure, not ours. A cloud robot loses its credentials to the same press. What
differs is only the distance to the cure: on cloud it is a two-minute "Update Network"
tap in the app, so it never registers as a persistent fault; locally it needs a
laptop, a BLE session and a completed provision. Same bug, different ergonomics.
Do not treat this as evidence that local provisioning is more fragile.

**The operational rule: do not put a robot into pairing mode unless you intend to
complete a provision.** Holding Connect is not a free diagnostic — it takes the robot
off the network until a provision finishes. Anything that asks a user to enter
pairing mode "just to look" (a probe, a diagnostic subcommand) has to say this.

**Ruled out by measurement, not argument:**

- **Signal** — both robots report -59..-65 dBm; they are indistinguishable.
- **The broker** — robot 1 held one session across the whole window and answers
  normally right now.
- **TLS / certificates** — mosquitto logged a keepalive timeout, never a handshake
  failure, and the robot's certificate is the one the broker had already accepted.
- **DHCP** — no lease churn for either robot across 12 days of dnsmasq logs.
- **Reset as a cause in itself** — routine in normal use, never reproduces this.

**Previously listed here as "unexplained: never happened on Whisker's cloud."
Resolved — it does happen there; the app just fixes it immediately.**

**Still worth confirming on the other unit** when a re-provision is cheap: put robot
1 into pairing mode, leave it alone, and check `ping -I br3` for `ARP INCOMPLETE`.
That would prove it is firmware behaviour rather than something specific to robot 2.
n=1 on one robot is what this rests on.

**Do not add warnings to `panel-reset` or the HA button on the strength of this.**
Reset in normal operation is not implicated.

---

## Added 2026-08-19 (parity check against the Whisker app)

### #81 — "Replace Filter" is the only app control whiskerless has no equivalent for

Screenshots of the Whisker app's Controls page (2026-08-19) list seven controls.
Six map onto things we already ship:

| App control | whiskerless |
|---|---|
| Power | `power`, HA `power_toggle` |
| Panel Lock | `keypad_lockout` switch |
| Lights | `night_light_mode` + brightness |
| Sleep Mode | sleep/wake times + `weekday_sleep` |
| Manual Cycle | `clean-cycle` |
| Reset Robot | `panel-reset` |
| **Replace Filter** | **nothing** |

We also ship several things the app does not: empty cycle, WiFi toggle, litter
calibration, hopper level and fill, litter distance in mm, RSSI.

**Whether Replace Filter is even reachable remotely is unresolved, and the evidence
cuts both ways.** `commands.md` states the filter wizard is unreachable because its
chord is a three-second hold and the write path declines holds. Against that, the app
plainly offers it. For it: pylitterbot's fifteen LR4 verbs contain no filter command,
and unlike Manual Cycle and Reset Robot — both of which show a confirmation dialog in
those screenshots — Replace Filter shows none, which is consistent with an in-app
wizard that talks the user through the panel hold rather than sending anything.

**If the app really does trigger it remotely, then a path exists that we have not
found — and finding it is the point of this item.** Our position is that hold-only
chords are unreachable because writing press type `02` produces no event and an
unknown type `00` is normalised to `01`. That is a statement about the panel-button
register `0x01`. It is NOT a statement that the function itself is unreachable: a
setting with a backing register is reachable by writing that register, which is how
lockout and the night light are already done, and how pylitterbot reaches settings
generally. The filter wizard was written off as having "no backing settings register
to write instead" — that is the claim to re-examine, not the hold.

**Do not re-test hold synthesis.** Writing type `02` has been tried and is inert;
that result stands and the repo's instruction not to spend another trial on it stands
with it. What is open is a *different* mechanism.

Settling it needs one observation: press Replace Filter in the app for a robot **on
Whisker's cloud** while capturing, and see whether any MQTT command reaches the robot
— and if one does, exactly what it is. Both robots here are local, so this needs one
deliberately left on cloud, or a capture taken before the next re-provision.

Candidate mechanisms to look for in that capture, in rough order of likelihood:

1. **A write to an unmapped settings register** that moves the globe to the filter
   position, the way `0x17` does lockout. `registers.md` still lists a number of
   registers with no known meaning.
2. **A type-2 macro opcode** other than the panel-button register — the class
   `NEVER_SEND_OPCODES` belongs to. Anything found here is refused by `safety.py`
   until it is understood, and must stay refused.
3. **Nothing at all** — the app walks the user through the physical hold and sends
   no command, which the absence of a confirmation dialog and of any filter verb in
   pylitterbot both hint at.

Outcome 3 would close this and vindicate the current documentation. Outcomes 1 or 2
mean `commands.md` is wrong that the function is unreachable, and the fix is to
classify whatever is found in `safety.py` before anything sends it.

**Not a gap:** per-cat weights (Arya/Nahla in the app). An activity CSV exported the
same day lists only unattributed per-visit weights, so cat identity is cloud-side
inference over the raw figure the robot reports. Nothing local can reproduce it, and
`pet_weight` already carries what the robot actually knows.

---

## Added 2026-08-19 (loose ends)

### #82 — Nobody has ever joined a hidden SSID with this, and the code says otherwise

`_choose_network` offers a `-` option that takes a typed SSID, and its comment
asserts "hidden SSIDs are real and the robot joins them fine; it just cannot list
them." **The CLI path is tested; the claim about the robot is not.** There is no
hardware evidence anywhere in this repo that an LR4 has ever joined a hidden
network — the phrase appears once, in that comment, with nothing behind it.

This is the inherited-confidence pattern the repo keeps catching: a plausible
assertion, written once, that reads like a finding. It matters because a user with a
hidden SSID is exactly the person who has no fallback — if the robot cannot join one,
the `-` option is a trap that costs them a stranded robot (see #80) rather than an
error message.

To settle it: hide an SSID on a test AP, provision a robot onto it, and record the
result. If it works, mark the comment PROVEN with a date. If it does not, the `-`
option needs to say so before it writes anything.

Cheap alternative if a hidden test network is inconvenient: the stock esp-idf
`prov-config` SetConfig carries only SSID and passphrase, with no "hidden" flag, so
whether the robot probes actively for a non-broadcast SSID is a firmware question a
capture of the app onboarding a hidden network would also answer.

---

## Added 2026-08-20

### #83 — Remove `whiskerless diagnose`: its useful verdicts are probably unreachable — **DONE 2026-08-24**

**Removed rather than qualified, as decided.** The subcommand, `_cmd_diagnose` and its
parser registration are out of `cli.py`; the man-page entry, the README section and the
`[Unreleased]` CHANGELOG bullet are out with it. The bullet was deleted outright rather
than reworded, because the command never appeared in a stable release.

**The library functions went too.** `wifi_diagnosis`, `diagnose_wifi` and the
`_describe_status` helper only reachable from them are removed from `ble/provision.py`
and from `ble/__init__.py`'s exports. The entry offered keeping them as bench tooling;
they had no other caller, and this repo's coverage floor makes an uncalled function a
liability rather than a spare part.

**Deleting covered code moves the ratio down, which the 3.11 job caught.** Removing 71
fully-covered statements while the uncovered remainder stayed fixed took the floor job
from exactly 99.00% to 98.98% - main had no margin at all there, and only the 3.11 leg
runs that close because the integration's PEP 695 tests skip on it. The answer was to
cover something real rather than move the floor: the pre-dispatch update nudge in
`main()` now has tests for all three things its comment promises - it reaches a person
watching, it stays out of a pipe, and a failure reading it does not take the command
down. 1318 tests, 99.14%.

**Decided 2026-08-20: take it out before 0.2.0 stable.** It shipped in
`v0.2.0-rc.35` and should not survive into the release.

The command reads the robot's WiFi status over BLE so that "blinking blue" becomes an
answer. Two problems, and the second is fatal:

1. **Its useful outputs duplicate `provision`.** `_verify_wifi` already raises on
   `AUTH_ERROR` ("almost always a mistyped WiFi password") and `NETWORK_NOT_FOUND`
   by name, at the moment those verdicts mean something — right after credentials
   are supplied and the robot attempts a join.
2. **Those verdicts are probably unreachable from `diagnose` at all.** Reaching the
   robot needs pairing mode, and pairing mode wipes the saved credentials and holds
   the station down (#80). A robot in that state has nothing to fail *against*, so
   there may be no `fail_reason` to report. **This was never tested** — the command
   was built and documented without checking that its advertised outputs can occur.

So it is a command that strands a robot (#80) to report, most likely, that the robot
is in the state the command itself caused.

**If anyone wants to save it instead**, the gate it should have passed first:
provision deliberately with a wrong passphrase, then run `diagnose` and see whether
`AUTH_ERROR` still appears. If it does, the command has a real use and only its
framing needs work. If it does not, remove it.

**What removal touches:** the `diagnose` subcommand and `_cmd_diagnose` in `cli.py`,
its parser registration, the man-page entry (a repo invariant test requires one per
subcommand), the README section, the CHANGELOG bullet, and the tests in
`test_provision.py`, `test_ble_provision.py` and `test_cli_robot_profiles.py`. The library
functions `diagnose_wifi` / `wifi_diagnosis` in `ble/provision.py` can stay as bench
tooling or go with it — they are not used elsewhere.

**Do not silently delete the coverage.** The repo holds a 99% floor with zero
uncovered statements; removing the command removes its tests too, which is fine, but
`wifi_diagnosis` staying without a caller would not be.

### #84 — The hold instruction states something false, and says it at length — **DONE 2026-08-24**

**Deleted, not rewritten, as the entry asked.** The provision hint now stops at "that is
pairing mode" and says nothing about advertising or holding through the scan. The README
transcript matches it. The `diagnose` hint that repeated it went with #83.

`ble/transport.py` keeps the behaviour and loses the story: `scan()` still documents
`timeout` as a ceiling that returns on the first answer, with the pairing-window rationale
and the bench-session anecdote dropped and no replacement cause invented in their place.
The same false clause is gone from the D-Bus comment, which keeps its real reason (BlueZ
raises a bare `OSError` that has to be wrapped). Both test docstrings that asserted the
false version now state the behaviour under test instead.

**The entry's list was not the whole list.** Searching for the *model* rather than the
sentence turned up seventeen more sites across twelve files, none of them named here:
comments and docstrings in `cli.py`, `provision.py` and `transport.py`, four test
docstrings, the README's reason for `setup` being a separate command,
`docs/design/authentication.md`, and three passages in the device captures. Each stated
or implied a window that expires when the button is released.

**The term went with the model.** "Pairing window" now appears nowhere in `src/`,
`tests/`, `docs/` or the README, because the phrase carries the expiry claim even where
the surrounding sentence does not. What the code needed to say in those places was
either "while the robot is in pairing mode" or "the robot is off the network until a
provision completes", and both are true. The two surviving uses are in closed backlog
entries above, left as the dated record of what was believed when they were written.

What survives is the distinction that matters: a robot in pairing mode is off the
network until a provision completes, which is a real cost worth designing around, but
nothing about it is timed. `scan()` returning on the first answer is kept as good
behaviour with no rationale attached, per the entry. The capture notebook keeps what the
bench session *observed* and now marks the going-quiet reading as superseded rather than
deleting it, because a failure that is still unexplained is worth leaving on the record.

**One touchpoint was already closed.** The CHANGELOG bullet's false rationale was removed
by `d6e27d1` when `[Unreleased]` was rewritten; nothing was left there to fix.

**Reported by the owner 2026-08-20.** The provision prompt tells the operator:

> Hold Connect on the robot now until its light BLINKS YELLOW (about three
> seconds) — that is pairing mode — and keep holding until the numbered steps
> below start. It only advertises while you hold, and the link is opened after
> the scan finds it.

**Everything after "that is pairing mode" is wrong.** The hold is a *transition*:
about three seconds puts the robot into pairing mode, and it stays there with the
button released. Nobody has to stand at the robot holding a button through a scan,
a network list, a prompt and a certificate write. #80 is the same fact from the
other side — pairing mode does not end on its own, nothing timed it out over half
an hour, and no button left it.

The shipped text contradicts itself inside one screen: the very next paragraph is
the banner explaining that the robot **stays** in pairing mode until a provision
completes, which cannot be true of a mode that ends when a finger lifts.

**The fix is a deletion, not a rewrite.** The whole instruction is: hold Connect
about three seconds, until the light blinks yellow. Say that and stop — the
operator does not need the advertising model, and it was wrong anyway.

**Where it is said:**

- `cli.py` — the `provision` hint (the block above), and the `diagnose` hint's
  "keep holding until the numbered lines below start". The "no LR4 found" error
  path is already correct and is the wording to match.
- `README.md` — the transcript reproduces the provision hint verbatim.
- `CHANGELOG.md` — the 0.2.0 bullet repeats the false rationale ("it only
  advertises while you hold the button, and the scan was spending that window").
  Fix the claim; do not delete the entry, the beep correction in it stands.
- `ble/transport.py` — the comment "the robot only advertises while somebody is
  holding its button". The `scan()` docstring's "only advertises while it is in
  **pairing mode**" is correct and stays.
- `tests/test_ble_transport.py` — two docstrings assert the false version.

**One thing to leave alone while fixing the prose.** `scan()` returning on the
first answer instead of running its window out is good behaviour and should not
change; only the reason attached to it is suspect. Its docstring cites a bench
session that found a robot and then failed to connect "because it had stopped
advertising" — with pairing mode persistent, that needs some other explanation, or
was misread at the time. Do not restate that anecdote as fact and do not invent a
replacement cause; drop the causal clause and keep the behaviour.

### #85 — With two robots saved, most commands neither ask which nor say which — **DONE 2026-08-20**

**Done together, as the entry asked.** `_pick_saved_robot()` offers a numbered list with the
default marked and the serial shown beside each name; it returns None rather than raising when
stdin is not a TTY, so scripts and CI keep exactly today's behaviour — the ambiguity error, non-zero,
no hang. It lives in the CLI layer: `resolve()` still raises, because it is a library call with
non-CLI callers.

**(b) went further than the entry described.** Announcing before a WRITE was not enough for the four
commands that ask first — `power`, `wifi-toggle`, `empty-cycle`, `clean-cycle` all confirmed BEFORE
resolving, so the person typing `yes` was never told which robot they were confirming for. That is
not informed consent, and `power` is the one where guessing wrong is unrecoverable. All four now
resolve first and name the robot inside the prompt itself: "Press Power on Upstairs?". This is the
`monitor` reasoning the entry pointed at, finally extended to its siblings.

**Reported by the owner 2026-08-20**, running `monitor`, `state` and `status` back
to back on a machine with two robots saved.

**Two halves, and the second is the one with teeth.**

**a) There is no picker, only an error or a silent default.**
`RobotProfileStore.resolve()` has three outcomes: an explicit `--serial`, the
default set by `use` (or written automatically at the end of `provision`), or the
single saved robot. With more than one saved and no default it raises
"several robots are set up (…) — pick one with `--serial`". Nothing ever offers a
choice, so the operator is sent away to run another command and start over.

The pattern to copy is already in this file: `_pick_robot()` prints a numbered
list of advertising robots and reads a selection. The store deserves the same,
listing serial, name and which one is currently the default.

**b) Only 2 of the 12 robot commands say which robot they acted on.**
`add_conn()` attaches `--serial` to: `status`, `calibrate`, `panel-reset`,
`monitor`, `state`, `read`, `set`, `send`, `cycle`, `empty`, `wifi`, `power`.
Only `monitor` ("monitoring LR4C… for 60s") and `status` (the serial as a header)
name their target. The other ten are silent — including every command that
**writes**: `set`, `send`, `cycle`, `empty`, `power`, `panel-reset`, `calibrate`.

So with two robots saved and a default set, `whiskerless power` toggles a robot
without ever printing which one, and a robot switched off has left the network —
nothing over MQTT brings it back. The reported case was `state`, which is
harmless; the same silence on `power` or `empty` is not. `monitor` already carries
a comment explaining the serial is resolved *before* the banner so it cannot print
"monitoring None" — that reasoning was never extended to its siblings.

**Design notes for whoever takes it:**

- **Prompt only on a TTY.** Scripts and CI must keep today's behaviour — the
  ambiguity error, non-zero, no hang. The repo already has this precedent (#63:
  provision skips its optional prompt when stdin is not a TTY).
- **A silent default is still worth naming.** Even when `resolve()` picks without
  ambiguity, the write commands should print the robot they are about to act on.
  Cheap, and it makes the "wrong robot" mistake visible at the moment it matters.
- **Do not prompt inside `resolve()`.** It is a library call used by non-CLI
  callers; the picker belongs in the CLI layer, with `resolve()` still raising.

### #86 — Naming a robot exists in the data model and nowhere in the UX — **DONE 2026-08-20**

**Asked by the owner 2026-08-20**, pointing at `dreame-valetudo` as the sister
implementation to copy from.

**Done with #85.** All three gaps closed: provisioning now offers a name (TTY only, enter to
skip), `whiskerless rename [robot] [name]` exists so relabelling no longer means re-provisioning —
which needs pairing mode, which wipes the robot's saved WiFi — and `--serial` accepts a display name
as well as a serial. The serial is tried FIRST, so a robot mischievously named after another
robot's serial cannot shadow the real one.

Kept a label, as the entry required: identity stays the serial for topics, the client-id, the
certificate CN and the profile directory. `rename` writes only `name`.

**Half of this is already built.** `RobotProfile.name` is stored, `display_name`
returns "the chosen name, else the serial", and `provision --name Upstairs` writes
it. `monitor`, `status`, `calibrate`, `robots` and `use` all print `display_name`
already. What is missing is every way to actually *get* a name in there:

1. **It is never offered.** `--name` is a flag and nothing more; provision never
   asks. The machinery is there — `_ask()` already prompts with defaults and TTY
   handling for the broker IP, the SSID and the backup path. `dreame-valetudo`
   collects the name during onboarding (`phases/recon.py` writes `ctx.pending_name`).
2. **There is no `rename`.** `_save_profile()` has exactly one caller: provision.
   So the only supported way to change a robot's label is to re-provision it —
   which means pairing mode, which wipes the robot's saved WiFi (#80, #84). That
   is an absurd price for a cosmetic relabel, and nobody will pay it.
3. **`--serial` takes only a serial.** Name a robot "Upstairs" and you still have
   to type `LR4C…` to select it. `dreame-valetudo`'s `_resolve_robot()` accepts
   the folder slug *or* the display name and dies with a list-pointing message on
   a miss.

**Why this is worth more here than in the sister repo: the serial is the sensitive
field.** The name is not a privacy risk — it is the privacy *fix*. A serial must
never reach a commit, a log, an issue, or a pasted terminal; `rc.25` is a
permanently contaminated PyPI artifact from exactly that, and the history rewrite
that followed could not reach four copies. Every header the CLI prints today
prints the serial by default, so every pasted session leaks one. With a name set,
`display_name` prints "Upstairs" instead and pasted output is safe by default —
including the per-command "acting on X" line #85 wants to add to the ten silent
write commands. Note the polarity is opposite to `dreame-valetudo`, where the
display name is the private field kept out of the anonymous bench slot.

**Do this with #85, not after it.** The picker that #85 asks for is the same code
path — it should list display names, and `dreame-valetudo`'s `_pick_robot()`
(numbered list of `display_name()` + a summary line, `die` with usage when stdin
is not a terminal) is a direct template for both.

**Keep the name a label.** Identity stays the serial: topics, the client-id, the
certificate CN and the profile directory must not key on it. `dreame-valetudo`
documents its rename as cosmetic for the same reason — identity lives in `config`
there, in the serial here — which is what makes renaming safe to offer at all.

### #87 — Drop the first-person voice from the README: it should read as technical, not personal — **DONE 2026-08-20**

**Done in both repos.** Whiskerless went from 13 hits to 3; dreame-valetudo from 4 to 0 (all four
were in the dnf/signing section, written the same day). The convention is now recorded in
`project-standard/CONVENTIONS.md` so the next document does not reintroduce it.

The three remaining hits here are deliberate and should stay: they are quoted CLI **output** —
the menu labels `I already have one — I will give you the files` and `my network is not listed`,
plus one passage quoting the first of those. That is the program speaking, not the document.

The load-bearing cases were rewritten rather than deleted. "our signing key" became "the SisyphusMD
signing key": the paragraph exists to distinguish that key from Forgejo's, so a passive or a bare
noun would have lost the distinction. The pairing-mode note kept its single-trial epistemics —
"on the unit we tested" became "on the one unit tested", which still says one unit.

**Asked by the owner 2026-08-20.** The README speaks as "we"/"our" in places where a
reference document should just name the thing. Second person stays — telling the
reader what *you* do is ordinary technical writing. This is about first person only.

**Where it is, measured — 11 in `README.md`, in two clusters that need opposite
treatment:**

**a) The packaging/signing section (6 hits) — a clean rewrite, and it fixes an
ambiguity.** "our signing key", "a package we signed", "adding that key alongside
ours", "which we deliberately do not ask you to trust". There is a precise noun
available in every case: the project's signing key, `CCE50015D058E9BF`, the
whiskerless repository definition. "Ours" versus "Forgejo's" is doing real
disambiguating work in that passage and a name does it better.

**b) The pairing-mode warning (4 hits) — rewrite carefully or make it worse.**
"On the unit **we tested**", "no button **we tried** left it", "`whiskerless
provision` is **ours**". Here the first person is carrying *evidence provenance*:
n=1, one robot, ESP 1.1.75. Flattening it to "no button leaves it" upgrades a
single-trial observation into an impersonal law, which is the exact failure this
project keeps having (see the PROVEN-means-live-tested rule and `safety.py`'s
docstring on the single-trial reboot). Impersonal phrasing that keeps the hedge:
"on the one unit tested (ESP 1.1.75)", "no button press found so far leaves it".
**Do not let the de-personalising edit strengthen a claim.**

**c) Line ~395, `Choose "I already have one"` — leave it alone.** That is a quoted
menu choice, i.e. the *user's* voice, and it must stay byte-identical to the string
`setup` actually prints.

**Also in scope, because the same sentence ships in the binary:** `cli.py`'s
pairing-mode banner prints "On the unit we tested it did not come back on its own"
and "no button we tried left it" — the README passage is a copy of it. Fix both or
they diverge. The man page is already clean.

**Boundary to decide before starting.** `docs/` holds ~30 more hits: the
device-protocol pages under `docs/devices/litter-robot-4/` should get the same
treatment as reference material, but `docs/backlog.md` (this file) and
`docs/reverse-engineering.md` are a working log and a narrative — first person
there marks who observed what, and stripping it costs provenance for no gain.
Recommendation: README, `cli.py` strings, and the protocol reference pages;
explicitly not the backlog or the RE story.

**Sibling repo.** `dreame-valetudo`'s README has the same problem at 4 hits.
Recorded here only — the convergence work across the two repos is being run from
that side.

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

## Added 2026-08-25

### #88 — Sweep the command surface, verified from telemetry rather than by eye

**Asked for 2026-08-25**, after the register sweep against the second robot. The read
sweep mapped what the robot *answers*; nothing has mapped what it *accepts*.

**#81 is the concrete target, and the reason this is not just exploration.** Replace Filter is
the one app control with no equivalent here, and #81's open claim is precisely that the wizard
was written off as having "no backing settings register to write instead" — a claim about the
register space that a write sweep is the right instrument for. Not the hold: writing press type
`02` is inert and that is settled. A backing register would be reachable the way lockout and the
night light already are. So the sweep has a success criterion beyond a census: a register whose
write moves filter state.

**The effect of a command is machine-detectable, which is what makes this worth doing.**
Proven against the seventh pass's own traffic: three synthesised panel presses appear on
the wire in that window, and diffing `/state` afterwards attributes an effect to a command with
nobody watching: `0x02010201` (CYCLE, short) showed `odometerCleanCycles` 8135→8136 at **+12s**.
So the sweep does not need a person confirming each code.

**The first attempt at this demonstration misattributed, which is the best evidence in the
entry.** It credited a `0x02010401` (RESET, short) press with an increment at +160s. That
increment was almost certainly the CYCLE press fired 2.5 minutes later — 01:26:20 against a press
at 01:26:11, a +9s latency matching the other cycle exactly — and the odometer increments at a
cycle's START. So RESET's own effect was never observed, a naive first-match detector produced a
confident wrong answer, and the real command latency is about ten seconds, not 160. So do not budget a verifier window for a
160-second effect that never happened — but do not size one to ten seconds either: the observed
cycle answered at +12s, which a 10s window misses, and an unknown register bounds nothing at all.
The rule that governs is one command per SETTLED window plus a command-specific signal, with the
observed 9-12s latency describing only the case already understood.

**A `/state` diff is correlation, and the robot acts on its own.** The verifier watches only the robot it
commanded, so the rate that matters is per robot and the two are not alike: over 5d07h the busier
one ran 129 cycles (one per 59 min, ~6.5% chance of an autonomous cycle inside a four-minute
window) and the quieter one 29 (one per 263 min, ~1.5%). Nearly all are cat-triggered. So a diff
would misattribute roughly one probe in fifteen on the busy robot — and sweeping the quiet one is
four times cleaner, which is worth choosing deliberately rather than by which robot is nearer. The verifier therefore cannot accept "something changed" as
acceptance. It needs a command-SPECIFIC signal: the register echo panel writes already produce
(live-proven on ESP 1.1.75, three trials, each echoing the register back with the documented
signature), or a transition that only that command could produce. Anything else — unrelated
telemetry, or none — stays UNRESOLVED rather than being scored either way.

**The third press is the design constraint.** It was missed, because it landed 2.5 minutes
after the RESET press while that cycle was still running, and the diff attributed the
change to the wrong command. So: ONE command per settled window — send, wait for idle,
diff, record — which sets the cadence at roughly four minutes rather than the protocol's
three seconds.

**Scope, and what the space actually costs.** A write is `0x02RRVVVV`: an 8-bit register
and a 16-bit value, so the full space is 256 x 65,536 = 16,777,216 sends — about 1.6 years
at 3s pacing, and not a candidate. What is tractable:

**Short press only — the hold is unreachable.** Writing press type `02` produces no event at
all, while an unknown type `00` is normalised to `01` and performed: the firmware recognises the
long press and declines it. Every hold-only chord is out of reach from MQTT, Whisker's own cloud
included, and that is settled — do not spend another trial on it. So the panel space is 2^5 - 1 =
**31 chords**, not 62.

| Sweep | Codes | At one settled window (~4 min) | With a 10s window |
|---|---:|---|---|
| Panel chords, captured short values | 4 | minutes | already what the tool sends |
| Panel chords, unobserved combinations | 27 | ~2 h | capture-first; not a sweep |
| One probe value per register | 256 | ~17 h | **~45 min** (but see below) |
| Every value of ONE chosen register | 65,536 | ~182 days | ~8 days |

The window is the whole cost, so choose it deliberately. A fixed settled window is correct and
expensive. A short window is affordable and can MISATTRIBUTE, though not in the way first written here: an autonomous cycle landing
inside the window is one risk, at the per-robot rates above, and a slow effect is another. The
CYCLE press answering in 9-12s bounds nothing for an unknown register: settings already commit
with variable latency and need read-verify-retry, so a delayed effect can overlap the next probe. And a short window is NOT justified by assuming most probes do nothing — that assumption is
the untested one. The 65,536-value sweep should be dropped rather than backgrounded: nearly every value in it is
unobserved and therefore DANGEROUS by this project's own classification, an unattended run cannot
be stopped when a physical effect appears, and running it at all contradicts the rule two
paragraphs down that unknown values are tested singly. It is listed here to price it, not to
recommend it.

**One probe value per register cannot map acceptance, which limits what that row is worth.**
The accepted value is unknown too, so a handler that only takes `1` reads as inert when probed
with `0`. A null result there is inconclusive rather than evidence of no handler, and the entry
should not be read as promising otherwise. Probe values need a reason — a neighbouring register's
range, a value seen in telemetry — or the row is a census of nothing.

**So the order of work is capture first, synthesis second.** Press the chords on the panel while
capturing, learn what the panel actually emits for each, then synthesise only those. That inverts
the appeal of this item — it needs a person at the robot for the part that produces the new
information, and the automated verification above is what makes the *replay* cheap, not the
discovery. Anything beyond captured values is a genuine experiment on an untested path and should
be run as one: deliberately, singly, and not as a sweep.

**Two claims were made while drafting this and both were wrong; they are recorded so the next
reader does not re-derive them.** First, that `0x1A`-`0x1C` being acknowledged and discarded
shows unhandled writes are harmless. It does not: those are *known computed* registers that
reject writes, and `safety.py` is explicit that "what a write to a register with no handler does
is simply untested". Second, that the panel bitmask space is safe because the firmware's
interlocks apply to a synthesised press as to a finger. That holds only for values the panel is
known to emit, and three things are being conflated when it is stated loosely:

- **Captured emissions:** four singles — Power, Cycle, Reset, Empty. The press that restored the
  robot emitted `0x010101`. Connect is NOT in this class: it is proven only by the robot vanishing
  when written, and `0x011001` may be permanently unobservable, since capturing it means watching a
  robot that has just taken itself off the network.
- **Classified SAFE:** only Cycle, Reset and Empty. Power and Connect are observed but take the
  robot off the air.
- **Unobserved:** the multi-button chords — with one exception that matters. Cycle+Empty is a
  CAPTURED emission: the panel produced `0x0A02` for the filter change. So that bitmask is
  observed; what is untested is its short-press form.

**That exception points at the experiment #81 wants, but the order is capture then send.**
Composing the captured bitmask `0x0A` with the working press type `0x01` does NOT yield a captured
value: classification is on the whole 16-bit value, and `0x0A01` has never been observed —
only `0x0A02`. So the trial is: press Cycle+Empty SHORT on the panel while capturing, and see what
the panel emits. If it emits `0x0A01`, synthesising `0x02010A01` is then a replay of a captured
value and is worth doing; if it emits nothing, that answers only the short-chord question — it does not
distinguish #81's other candidates (an app-written settings register, a separate macro, or a
UI-only wizard), and the cloud capture #81 asks for stays the way to settle those.
Either way it is one physical press and one observation, not a sweep — and it does not re-test the
hold, which is settled.

The established procedure already covers this: `commands.md` says capture an unknown button
value physically before writing it. That is not a formality to label around.

**What stays out is four opcodes, not the range.** `0xA3`, `0xA4`, `0xAC` and `0xAD` are
refused unconditionally — reset/OTA orchestrator, globe-motor OTA, flash erase, hardware reset.
Why they behave as they do is not known here — mutual TLS establishes who may publish, not what a
handler does with what arrives, and `safety.py` is deliberate about refusing that set on cost
rather than on any claim about mechanism. The rest of `0xA0`-`0xAE` is NOT excluded here, and excluding it would defeat the
point: #81's own candidate for Replace Filter is a distinct type-2 macro, and "cycle and reset are
reachable through `0x01`" says nothing about a filter macro. `0xA2`, `0xA5`, `0xA6`, `0xA8`,
`0xAA`, `0xAB` are unmapped and are exactly where such a macro would live — but they sit between
flash erase and OTA staging, so the way to investigate them is #81's cloud capture, which reveals
the opcode AND its value without guessing either.

**Two buttons take the robot off the air, not one.** Power can leave it off and unreachable,
and Connect toggles wifi — proven to silence the robot within 0.8s. Silence is indistinguishable
from "did nothing", so both classes need a person nearby. Only **7** of the 31 chords exclude both — and 4 of those 7 are still unobserved combinations,
so the genuinely unattended set is the **3 classified SAFE single presses** the tool already sends
— Cycle, Reset, Empty. Power is captured but takes the robot off the air; Connect is neither.
Everything else is attended work by definition, which is the honest shape of this item.

**Do not assume all 31 bitmasks are real panel events.** Cycle, Reset and Empty short presses are
what the catalogue actually evidences; the rest are combinations nobody has seen the panel emit.
`commands.md` says to capture an unknown button value physically before writing it, and that
instruction applies here — a chord that no panel produces is a write of an unobserved value, which
is a different experiment from synthesising a press, and should be labelled as one.

## Added 2026-08-27

### #89 — Provision from Home Assistant itself, rather than only from the CLI — **discuss**

**Asked for 2026-08-27.** Today provisioning is a CLI activity: install `whiskerless[ble]` on a
laptop, carry it to the robot, hold the button. Every HA user therefore meets a second tool before
the integration can see anything. Many HA installs already have Bluetooth — a built-in adapter, or
an ESPHome Bluetooth Proxy that may well be closer to the litter box than any laptop — so the
hardware to do this is usually already in the house and already talking to HA.

**Why this is `discuss` and not `open`.** It reopens a boundary that today's dependency layout was
built around, so the design has to come first.

- **The integration deliberately does not depend on `bleak`.** `manifest.json` pins
  `whiskerless==<version>` with no `[ble]` extra, and nothing under `custom_components/` imports BLE
  code. That is why `ble/transport.py` and `ble/provision.py` defer their bleak imports at all. HA
  also does not want raw bleak in an integration: it owns the adapter through its `bluetooth`
  component and hands out `BLEDevice`s. So the question is not "add bleak to the manifest" — it is
  whether `provision.py`'s transport can accept a connection HA supplies, instead of opening one.
- **Bluetooth proxies are the interesting half and the risky half.** A proxy near the robot removes
  the "stand next to it with a laptop" step entirely, which is most of the value here. But
  provisioning is a full GATT write session, not passive advertisement scraping, and proxies have a
  bounded number of active connection slots. Whether a proxy can hold a provisioning session for its
  whole duration, reliably, is the first thing to establish — on hardware, not from documentation.
- **Whether the CA *signing key* enters Home Assistant is a design choice, not a given.** It is
  only forced if HA issues the certificates itself. `ProvisioningConfig` already takes optional
  pre-issued `client_cert`/`client_key`, and `docs/setup/certificates.md` documents `--auth
  supplied` for precisely the arrangement where the signing key lives elsewhere — cert-manager,
  Vault, an offline root. In that mode nothing issues on demand: an external issuer produces the
  robot's identity beforehand and whiskerless only stores and presents it. That is the design to
  try first, and `--auth anonymous` is a third option.

  Be exact about what HA would still hold, because the two are easy to conflate: `ca_pem` is
  required on every path and `provision_robot()` always writes it, so HA receives the **public**
  `ca.crt` regardless. That is not the sensitive half. Keeping the **private** signing key out is
  the property worth designing for; putting it in HA's config directory is a fallback to argue for
  explicitly, with `docs/setup/` and the backup story revisited before it, not after.
- **The button hold stays physical regardless.** Nothing here removes the trip to the robot to put
  it in provisioning mode; it removes the laptop, not the walk. Worth being honest about in any UX
  sketch, because "provision from HA" sounds like it removes both.

**Not a dreame-valetudo item.** It has no Home Assistant surface at all, which
`project-standard/VARIANCE.md` already records as the one channel whiskerless has and it does not.


### #90 — Tell "the robot is not on the broker" apart from "the robot is not answering" — **discuss**

#21 surfaced this. Both conditions render identically as `unavailable`, and they need opposite
responses: a robot that has stopped answering state requests may come back on its own, while a
robot whose MQTT client has wedged will not — it needs a power cycle, and no amount of waiting
or reloading the config entry changes that. On 2026-08-28 the second case looked exactly like
the first for ten hours.

The distinction is visible to the broker but not, today, to us. Two directions worth weighing:

- **A last-will topic.** If the robot registers an LWT, the broker announces the disconnect and
  the integration learns the difference for free. Whether LR4 firmware supports one is unknown
  and has to be checked against a real unit before any of this is designed around it.
- **Infer it — but only weakly.** Telemetry is push and arrives every few seconds, so
  *continuing* traffic while a heartbeat goes unanswered does prove the robot is still on the
  broker. The converse does not hold: a connected robot that stops publishing looks exactly
  like one whose session has dropped, so total silence cannot establish that it is off-broker
  or that a power cycle is required. Any wording built on silence alone has to stay hedged,
  which is why the LWT question decides whether this is worth doing at all.

The user-facing half matters more than the mechanism: the point is to say "this robot has gone
off the broker and will not return by itself" rather than a bare `unavailable`, so nobody spends
a morning on packet captures again. Do not design the wording around one incident's specifics —
confirm the LWT question first, since it decides which of the two shapes is even available.
