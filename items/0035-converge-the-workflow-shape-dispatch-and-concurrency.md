# #35 Converge the workflow shape: dispatch and concurrency

- Kind: pull, state: closed, by cody, created 2026-08-24T10:38:31-07:00
- Labels: none; milestone: none
- refs/pull/35/head -> main, merged: True

A workflow-shape audit across all 14 shared workflows, after an earlier convergence pass checked Renovate identities, action pins and install channels but never looked at triggers or concurrency.

Three divergences, each repo missing something the other had:

- `.forgejo/ci.yml` had `workflow_dispatch` in whiskerless only. Forgejo has no rerun API, so dreame main was stranded red by a cluster-wide network outage with no way back except an unrelated commit.
- `.forgejo/ci.yml` had per-ref concurrency in whiskerless only, so dreame left superseded runs competing for runners.
- `.forgejo/publish.yml` had per-tag serialisation in dreame only, so whiskerless publishing was not deduplicated at all.

Both publish groups now key on the FULL ref: `ref_name` drops refs/heads and refs/tags alike, so a branch sharing a tag name would share its group, and publish.yml is dispatchable.

Guards mirrored into both, each mutation-verified.
