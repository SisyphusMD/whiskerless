# #230 Generate the Home Assistant OS Mosquitto listener during setup

- Kind: pull, state: closed, by cody, created 2026-11-18T07:33:00-08:00
- Labels: none; milestone: none
- refs/pull/230/head -> main, merged: True

## What and why

Setting up the official Home Assistant OS Mosquitto app previously meant translating a generic broker example into a custom listener by hand. `whiskerless setup` now writes `broker/haos/whiskerless.conf` on the provisioning computer for both certificate-based authentication modes, including on an existing setup. The guide walks through the Home Assistant controls and explains how to check whether port 8883 is already occupied. Once installed, the listener accepts another supported robot provisioned with a certificate from the same CA.

Closes #229. Related to #190.

## Sibling repo

- [x] Not applicable. The listener is for robots provisioned with a whiskerless client certificate. Dreame Valetudo uses a different MQTT provisioning flow.

## Checks

- [x] The new setup tests failed on the parent commit because the listener file was missing. The library suite passed on Python 3.13 (1,500 passed) and Python 3.11 (1,499 passed, one interpreter-specific skip). Coverage exceeded 99% on both.
- [x] All 41 files covered by `STANDARD.lock` matched. Ruff, strict mypy, documentation links and Markdown lint on changed lines passed.
- [x] In an isolated instance of the official Mosquitto 7.1.3 image, two simulated robots authenticated with separate certificates and exchanged messages with a password-authenticated client on the same broker. It rejected an untrusted certificate, a missing certificate, an incorrect password and an anonymous connection on port 1883.


## forgejo-actions, 2026-11-18T07:33:51-08:00

<!-- ai-review -->
**AI review** of `c301e581de`: Clean PR that generates a Home Assistant OS Mosquitto listener config during setup, with thorough documentation, good test coverage of the new feature and its edge cases (bad key, anonymous/supplied modes, re-run), and a sensible cert/key validation guard. No blocking issues found.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
