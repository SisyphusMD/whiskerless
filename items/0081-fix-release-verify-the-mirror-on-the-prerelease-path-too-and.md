# #81 fix(release): verify the mirror on the prerelease path too, and compare the tag object

- Kind: pull, state: closed, by cody, created 2026-08-29T13:59:59-07:00
- Labels: none; milestone: none
- refs/pull/81/head -> main, merged: True

Two gaps behind the same symptom that failed rc.41.

`prerelease.yml` deliberately does NOT call `packaging/push-tag.sh` - it inlines the tag push because that step is where the repo-write PAT reaches shell and the workflow is dispatchable from any branch, so it must not execute a script read back off the checkout. The consequence was that v0.1.22's mirror confirmation never reached the path that actually cuts rcs. The verification half needs no credential, so it goes inline as workflow-defined text: an unauthenticated GET against a slug the runner supplies.

And confirming by HTTP status alone was not enough. An rc number is derived from the source tags, so a name is reusable, and a ref left behind by a partial prune answers 200 while still pointing at the previous release. Both the inline copy and the shared helper now compare the object the mirror serves with the one just pushed (project-standard v0.1.23, vendored here).

The POST is bounded too - unbounded, a stalled sync would have prevented the readback from ever running.
