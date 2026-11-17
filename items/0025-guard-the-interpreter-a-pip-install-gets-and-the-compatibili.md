# #25 Guard the interpreter a pip install gets, and the compatibility floors

- Kind: pull, state: closed, by cody, created 2026-08-23T06:32:47-07:00
- Labels: none; milestone: none
- refs/pull/25/head -> main, merged: True

Two invariants, both mirrored in dreame-valetudo.

**pip needs its own Python.** A job that pip-installs into the runner image's interpreter dies on PEP 668. Nothing in a workflow says which Python a step gets, so this stays invisible until an image changes under a job that worked for months. It hit dreame's tap job mid-release, after the tag was cut.

**A compatibility floor has to stay old.** Renovate cannot tell a floor from a current-release alias; unclamped it bumps the tag and the leg becomes a second current test — green, proving nothing.
