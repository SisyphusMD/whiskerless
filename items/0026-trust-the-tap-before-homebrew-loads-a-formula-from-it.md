# #26 Trust the tap before Homebrew loads a formula from it

- Kind: pull, state: closed, by cody, created 2026-08-23T08:33:50-07:00
- Labels: none; milestone: none
- refs/pull/26/head -> main, merged: True

Homebrew refuses to LOAD a formula from an untrusted third-party tap. Building the rc bottle loads the stable formula too, because the rc formula's `conflicts_with` names it.

That means this only bites once a stable formula exists in the tap. dreame-valetudo has one, so every bottle job on rc.17 and rc.18 died with `Refusing to load formula ... from untrusted tap`. whiskerless has no stable formula in the tap yet, so it was passing on an absence rather than on correctness — and would have broken the first time 0.2.0 shipped.

Guarded on the subcommand existing, not on its exit status: an older Homebrew has no `trust` and needs none, while a `trust` that exists and fails is a real problem and must stop the build.
