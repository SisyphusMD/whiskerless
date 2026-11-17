# #51 Start the install matrix when the release is ready

- Kind: pull, state: closed, by cody, created 2026-08-25T20:23:54-07:00
- Labels: none; milestone: none
- refs/pull/51/head -> main, merged: True

The Linux install matrix triggered on the tag push — the same instant `publish.yml` starts — so its wait job held one of the runner's few slots for its entire budget, polling for artifacts the publish it was starving had not built yet. Measured on rc.48: the publish pipeline did ~14 minutes of real work but took 50, with 15- and 21-minute gaps where no publish job was running at all.

Forgejo has no `workflow_run`, so the finished publish now says so explicitly: `install-matrix.yml` is dispatch-only, and `publish.yml` hands it the tag after every producer plus `reconcile` settles.

It runs even when a producer reported failure, deliberately: a destination can fail its upload and `reconcile` can then heal the release across registries, leaving a COMPLETE release whose handoff had been skipped — a release with no install matrix at all. `wait-for-release.sh` remains the authority on whether the release is genuinely installable.

Also pins a gap neither project had covered: nothing asserted that `build-linux-arch.sh` smokes BOTH package formats before publish, so the `.rpm` gate could have been dropped without anything noticing.

The GitHub half deliberately stays on tag push — it runs on GitHub-hosted runners, so its waiting does not starve this runner, and a trigger that cannot silently fail is worth more there.
