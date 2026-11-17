# #169 ci: run hassfest and the HACS checks in Forgejo CI too

- Kind: pull, state: closed, by cody, created 2026-11-16T10:04:06-08:00
- Labels: none; milestone: none
- ci/hassfest-hacs-in-house -> main, merged: True

Step 3 of the GitHub runner exit, part 1 of 2. Adds `hassfest` and `hacs` jobs to Forgejo ci.yml, beside GitHub's hassfest.yml.

- hassfest: Home Assistant's own image, pinned by digest through the image mirror, copied in with docker create + cp (a bind mount from the job container mounts nothing).
- hacs: the HACS action image, pinned by digest, run against the GitHub mirror at this exact commit after waiting for the push mirror to carry it. INPUT_REPOSITORY is set so the full 10-check set runs (without it HACS treats the run as a fork PR and runs 5); the job fails if fewer than 10 ran.
- Proven locally: hassfest valid on main and fails on a broken manifest; HACS 10/10 at edcef22 (same 10 checks as GitHub run 43802314100).

Not required checks and not in the `macos` job's needs. Part 2 deletes hassfest.yml (plus its GITHUB_ONLY entry, retry watch-list entry, macos-scope regex + test, ci-split.md bullet) after 5 main pushes green on both.

dreame-valetudo has no Home Assistant surface, so this step has no sibling change (VARIANCE.md HACS row).
