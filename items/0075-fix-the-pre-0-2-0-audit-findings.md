# #75 Fix the pre-0.2.0 audit findings

- Kind: pull, state: closed, by cody, created 2026-08-28T19:48:01-07:00
- Labels: none; milestone: none
- refs/pull/75/head -> main, merged: True

From a cold audit of v0.1.3..main.

**Privacy.** A real robot hardware address was in two shipped docs and, in packed form, in a test fixture. It is in the sdist that hatchling builds, so a stable tag would have made it permanent — the same shape as the rc.25 serial. Removed, and a guard added: it matches colon, hyphen and bare-hex spellings, judges runs by length so an IPv6 address in two-digit groups does not trip it, and treats a run containing an approved fixture as that fixture.

**Security docs.** authentication.md and pki.py both said a robot private key is never stored. It is, at robots/<serial>/client/ — the same file said so 180 lines earlier. Corrected, with the real reasons (broker identity and ACL continuity; supplied-mode credentials cannot be reissued) and the cost stated plainly.

**README.** Told first-time users the first provision offers to create the CA. provision refuses exactly that and says to run setup.

**CHANGELOG.** Adds the status command and the removed send --allow-motor flag.
