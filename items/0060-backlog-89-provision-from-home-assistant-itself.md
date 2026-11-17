# #60 Backlog #89: provision from Home Assistant itself

- Kind: pull, state: closed, by cody, created 2026-08-27T08:47:54-07:00
- Labels: none; milestone: none
- refs/pull/60/head -> main, merged: True

Records the idea for discussion: HA already owns a Bluetooth stack and often a proxy nearer the robot than any laptop. Notes the three things that make it a design conversation rather than a task — the integration deliberately has no bleak dependency, proxy connection slots have to be proven on hardware, and the certificate handoff should use an external issuer so the CA signing key stays out of HA.
