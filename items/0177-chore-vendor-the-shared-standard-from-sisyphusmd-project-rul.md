# #177 chore: vendor the shared standard from SisyphusMD/project-rules 0.2.0

- Kind: pull, state: closed, by cody, created 2026-11-16T16:10:53-08:00
- Labels: none; milestone: none
- refs/pull/177/head -> main, merged: True

## What and why

SisyphusMD/project-standard is retired into SisyphusMD/project-rules (project-rules#22), which now carries the same `shared/` and `tools/` under one public rulebook. This re-vendors from project-rules v0.2.0 and moves every pointer to it:

- `STANDARD.lock`: source repo, tag v0.2.0, commit 156f8c1. Only two vendored files change, and only to name the new repo: `revendor-standard.sh` clones project-rules, and `check-standard-sync.py`'s drift message names it.
- `release-pins.env`: `PROJECT_STANDARD="0.2.0"` with `depName=SisyphusMD/project-rules`, and the matching `.renovaterc.json` package rule, so Renovate follows the new repo's tags.
- Doc and comment references: `project-standard/VARIANCE.md` is now `project-rules/VARIANCE.md`, CONVENTIONS.md is split into `project-rules/conventions/` (the old "6c" is `shell-and-workflows.md` section 4, the first-person rule is in `code.md`).

project-rules is public, so the anonymous clone in `revendor-standard.sh` and Renovate's tag lookup both work.

## Sibling repo

- [x] Ported to the sibling repo: SisyphusMD/dreame-valetudo#279

## Checks

- [ ] Regression test that fails on the parent commit (n/a: no behaviour change; the invariant tests that read the pin and lock pass)
- [x] `STANDARD.lock` still in sync (`check-standard-sync.py`: 41 files match v0.2.0)
