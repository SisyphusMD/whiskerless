# #227 Publish Whiskerless Homebrew formulae and bottles through tap PRs

- Kind: pull, state: closed, by cody, created 2026-11-17T19:55:34-08:00
- Labels: none; milestone: none
- refs/pull/227/head -> main, merged: True

Closes #224.

Pin the verified homebrew-tap #11 merge at c8bb9a5b3a54c841375a5a3b619c98a377cb75be. Render without a tap credential and use the isolated submit job to wait for the exact changed paths on main. Build bottles after the source formula and keep the same-tag repair path with current tooling and original tagged templates. Preserve the standard lock.

147 focused release and workflow tests, strict workflow YAML lint, the standard drift check, and Bash fixtures for exact waits passed. The real publisher proof still needs a separately approved release candidate.

Large diff: Keep the matching credential-isolated submit, bottle prerequisites, recovery dispatch and validation in one publisher change so releases keep their full source and bottle ordering.

## forgejo-actions, 2026-11-17T19:59:43-08:00

<!-- ai-review -->
**AI review** of `a7373307e3`: The PR correctly splits tap writes into credential-free render jobs and a credential-bearing submit workflow that opens a PR and waits for the exact files to land on main. Credential isolation, ordering (formula → bottles → prune/install), the pinned helper commit, path-traversal guard, and the updated tests all check out; docs and CHANGELOG are updated in the same PR.

### Withdrawn

- **F1** (blocking, `.forgejo/workflows/submit-tap-formula.yml:3`) Missing `secrets` declaration in `workflow_call` — token will be empty at runtime: The `on.workflow_call` block declares only `inputs`. All three callers pass `secrets: tap-token: …`, and the job body reads `${{ secrets.tap-token }}`. Under GitHub/Forgejo Actions semantics a reusable workflow receives only the secrets explicitly listed under `on.workflow_call.secrets`; without that declaration `secrets.tap-token` resolves to the empty string.
  - Reviewer: Withdrawn. The author showed a concrete Forgejo pre-execution rejection (run #1806: `workflow_call only supports keys "inputs" and "outputs", but key "secrets" was found`) and the Forgejo 17 documentation for `jobs.<job_id>.secrets`. Forgejo passes the alias through the caller's `secrets:` key on the calling job, which all three callers here use. The test's `== {"inputs"}` assertion correctly locks the Forgejo schema.


Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W3siaWQiOiAiRjEiLCAiZmlsZSI6ICIuZm9yZ2Vqby93b3JrZmxvd3Mvc3VibWl0LXRhcC1mb3JtdWxhLnltbCIsICJsaW5lIjogMywgInNldmVyaXR5IjogImJsb2NraW5nIiwgInN0YXR1cyI6ICJ3aXRoZHJhd24iLCAidGl0bGUiOiAiTWlzc2luZyBgc2VjcmV0c2AgZGVjbGFyYXRpb24gaW4gYHdvcmtmbG93X2NhbGxgIFx1MjAxNCB0b2tlbiB3aWxsIGJlIGVtcHR5IGF0IHJ1bnRpbWUiLCAiZGV0YWlsIjogIlRoZSBgb24ud29ya2Zsb3dfY2FsbGAgYmxvY2sgZGVjbGFyZXMgb25seSBgaW5wdXRzYC4gQWxsIHRocmVlIGNhbGxlcnMgcGFzcyBgc2VjcmV0czogdGFwLXRva2VuOiBcdTIwMjZgLCBhbmQgdGhlIGpvYiBib2R5IHJlYWRzIGAke3sgc2VjcmV0cy50YXAtdG9rZW4gfX1gLiBVbmRlciBHaXRIdWIvRm9yZ2VqbyBBY3Rpb25zIHNlbWFudGljcyBhIHJldXNhYmxlIHdvcmtmbG93IHJlY2VpdmVzIG9ubHkgdGhlIHNlY3JldHMgZXhwbGljaXRseSBsaXN0ZWQgdW5kZXIgYG9uLndvcmtmbG93X2NhbGwuc2VjcmV0c2A7IHdpdGhvdXQgdGhhdCBkZWNsYXJhdGlvbiBgc2VjcmV0cy50YXAtdG9rZW5gIHJlc29sdmVzIHRvIHRoZSBlbXB0eSBzdHJpbmcuIiwgInJlc3BvbnNlIjogIldpdGhkcmF3bi4gVGhlIGF1dGhvciBzaG93ZWQgYSBjb25jcmV0ZSBGb3JnZWpvIHByZS1leGVjdXRpb24gcmVqZWN0aW9uIChydW4gIzE4MDY6IGB3b3JrZmxvd19jYWxsIG9ubHkgc3VwcG9ydHMga2V5cyBcImlucHV0c1wiIGFuZCBcIm91dHB1dHNcIiwgYnV0IGtleSBcInNlY3JldHNcIiB3YXMgZm91bmRgKSBhbmQgdGhlIEZvcmdlam8gMTcgZG9jdW1lbnRhdGlvbiBmb3IgYGpvYnMuPGpvYl9pZD4uc2VjcmV0c2AuIEZvcmdlam8gcGFzc2VzIHRoZSBhbGlhcyB0aHJvdWdoIHRoZSBjYWxsZXIncyBgc2VjcmV0czpgIGtleSBvbiB0aGUgY2FsbGluZyBqb2IsIHdoaWNoIGFsbCB0aHJlZSBjYWxsZXJzIGhlcmUgdXNlLiBUaGUgdGVzdCdzIGA9PSB7XCJpbnB1dHNcIn1gIGFzc2VydGlvbiBjb3JyZWN0bHkgbG9ja3MgdGhlIEZvcmdlam8gc2NoZW1hLiJ9XQ== -->

## cody, 2026-11-17T20:01:53-08:00

F1 applies GitHub’s declaration requirement to Forgejo. Our installed Forgejo actually rejected the suggested declaration before any job ran in Dreame run #1806. Its pre-execution diagnostic says `workflow_call only supports keys "inputs" and "outputs", but key "secrets" was found`. Forgejo 17 documents that a caller maps the selected secret under `jobs.<job_id>.secrets`, which makes that alias available to `secrets` in the called workflow. The helper and all three callers here use the same `tap-token` alias. Thus the test intentionally enforces the installed Forgejo schema, and the live release proof remains planned for verifying the runner paths.

https://forgejo.org/docs/v17.0/user/actions/reference/#jobsjob_idsecrets

https://forgejo.bryantserver.com/SisyphusMD/dreame-valetudo/actions/runs/1806
