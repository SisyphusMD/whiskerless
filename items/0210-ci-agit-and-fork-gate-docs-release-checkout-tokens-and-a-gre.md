# #210 ci: AGit and fork gate docs, release checkout tokens, and a green HACS job

- Kind: pull, state: closed, by cody, created 2026-11-17T13:21:33-08:00
- Labels: none; milestone: none
- refs/pull/210/head -> main, merged: True

Follow-ups to the AGit trust gate (SisyphusMD/project-rules#79), plus the red HACS job on main. One commit per issue.

- **#207 (docs).** `CONTRIBUTING.md` now says fork pull requests get no CI either and that a maintainer pushes the change to a branch here to run it. The install-matrix bullet no longer contrasts "here" with "on Forgejo" (both are Forgejo now): it runs at release time or on dispatch, never on a pull request. The trust-gate test already checks every `pull_request` job, so a job with no `if:` fails it; unchanged.
- **#208.** Every checkout in `publish.yml` and `prune-rcs.yml` sets `persist-credentials: false`. No job there pushes this repository; the Homebrew tap jobs clone and push another repository with their own explicit header. New test: every checkout in both workflows disclaims the token (it fails on main, naming seven jobs); the prune-dispatch test now expects the key.
- **#209.** `CI / HACS (repository validation)` failed one check on main: `issues`, because the GitHub mirror is read-only with issues off on purpose and the manifest's `issue_tracker` points at Forgejo. Home Assistant's Marketplace docs (contributors.home-assistant.io/marketplace) still name `hacs/action` with `category: integration`; this job already runs that action's own image, pinned to the current `main` digest. It now passes `INPUT_IGNORE=issues` and requires the other nine checks. The manifest gains `"categories": ["pets"]`, which the run reported as a warning. New test: the job's `docker run` carries exactly `-e INPUT_IGNORE=issues` and the floor is nine; it fails on main and if the option moves into a comment. Listing in the Marketplace's default catalog would not accept a skipped check, so that would first need issues on in the mirror; not proposed here.

Closes #207
Closes #208
Closes #209


## cody, 2026-11-17T13:24:52-08:00

Status: pushed at 6d72a8c, cx review finding fixed (HACS test asserts on the docker command). Needs CI, including the live HACS job, which should now report 9 checks passed. Not merged. Session handed off to Codex.
