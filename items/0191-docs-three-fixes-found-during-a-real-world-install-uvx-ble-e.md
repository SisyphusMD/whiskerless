# #191 docs: three fixes found during a real-world install (uvx BLE extra, stale recovery note, CA keyUsage)

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:25-08:00
- Labels: none; milestone: none

_Recreated from GitHub pull request [#1](https://github.com/SisyphusMD/whiskerless/pull/1), opened by @CryingPecan on 2026-07-27, when the GitHub copy became read-only._

_This is a record of the pull request, not the pull request itself: its commits are kept in the maintainer's archive and were not pushed here._

---

Hey Cody — it's Brent. I put my downstairs Litter-Robot 4 (with LitterHopper, ESP firmware 1.4.4) onto whiskerless today with an EMQX broker on HAOS. Provisioning, telemetry, and settings round-trips all work — really impressive project. Three doc issues bit me on the way through, fixed here:

1. **README: the one-shot `uvx whiskerless provision` doesn't work** — it errors with `BLE provisioning needs the 'ble' extra`. The working form is `uvx --from 'whiskerless[ble]' whiskerless provision`; updated the three spots (incl. the Windows section).

2. **recovery.md still describes a confirmation-gated clean-cycle command** — contradicts README/compatibility.md, which say no motor command ships (since 0xA3 turned out to be a reset). Reworded to match.

3. **certificates.md CA recipe breaks the CLI on Python 3.13** — the generated CA has no `keyUsage` extension, and 3.13's default `VERIFY_X509_STRICT` rejects it (`CA cert does not include key usage extension`) even though the robot's mbedTLS accepts it. Added `-addext` lines plus a note with the Python 3.12 workaround for already-provisioned CAs.

Heads-up on what's coming: I'm gathering a few days of raw wire captures from my robot — ESP 1.4.4 shows some enum/value drift vs the documented 1.1.x maps (new robotCycleStatus/State integers, litter-level % scaling), the local state doc carries `DisplayIntensityHigh/Low` (panel-brightness entity candidate), and notably **no hopper fields appear in the local state doc even with a hopper attached and enabled**. Planning follow-up issues/PRs with the data — happy to test anything on real hardware, my second LR4 is still on the cloud if you need cloud-side captures.

## cody, 2026-11-17T08:59:25-08:00

_@SisyphusMD on GitHub, 2026-08-09:_

Merged into `main` on the Forgejo source of truth (this mirror is read-only, so GitHub can't auto-close it). Your commits are preserved with you as author; the Claude Code trailers were stripped during the rebase, and the multi-paragraph bodies became single-line subjects to match the repo's commit convention. The rationale from your PR descriptions has been folded into the docs and CHANGELOG instead.

Shipping in 0.2.0. I'll send you a longer write-up separately — your work turned up something significant about our own `robotStatus` map that changed what we merged.
