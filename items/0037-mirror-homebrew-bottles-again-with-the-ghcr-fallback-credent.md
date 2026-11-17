# #37 Mirror Homebrew bottles again, with the ghcr fallback credential restored

- Kind: pull, state: closed, by cody, created 2026-08-24T14:02:49-07:00
- Labels: none; milestone: none
- refs/pull/37/head -> main, merged: True

Re-lands the bottle mirroring reverted earlier, with the reason it was reverted actually fixed.

Setting `HOMEBREW_ARTIFACT_DOMAIN` makes Homebrew suppress the anonymous `Authorization: Bearer QQ==` it would otherwise send to ghcr.io, so any bottle the mirror could not serve fell back bare and got a 401. `HOMEBREW_DOCKER_REGISTRY_TOKEN=QQ==` restores exactly that anonymous credential: ghcr.io answers 200 for it (verified directly) and the mirror ignores it, so a mirror miss downloads the bottle instead of failing the job.

Measured from a runner rather than a workstation: a cold entry syncs in about 21s against the roughly 7s Homebrew's default three retries allow, which is what the raised retry budget is for; a 170MB bottle already synced serves in about 2s. The repo invariant now fails if either the credential or the retry budget is dropped while a mirror is set.
