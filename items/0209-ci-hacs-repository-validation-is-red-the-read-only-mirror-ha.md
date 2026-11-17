# #209 CI / HACS (repository validation) is red: the read-only mirror has issues off

- Kind: issue, state: closed, by cody, created 2026-11-17T13:11:50-08:00
- Labels: none; milestone: none

`CI / HACS (repository validation)` is red on main (71fb42f): 9 of 10 checks pass and `issues` fails with "The repository does not have issues enabled".

The action validates the GitHub copy, because that is what Home Assistant's Marketplace (HACS until 2026.11) installs from. That copy is a read-only mirror with issues turned off on purpose; issues go to Forgejo, which the manifest's `issue_tracker` already names. The validation reference (contributors.home-assistant.io/marketplace/reference/validation/) still names `hacs/action` with `category: integration`, and its `ignore` input exists for checks that do not apply to your own runs.

Plan:
- Keep the action as it is, the image `hacs/action` itself runs, pinned by digest (already the current `main` digest), since this job runs it directly rather than through `uses:`.
- Ignore the `issues` check only, with the reason in the workflow, and require exactly the other nine to pass rather than "at least 10".
- Add the manifest's `categories` (`pets`), which the run currently reports as a warning.

Note for later: the Marketplace catalog does not accept ignored checks, so listing Whiskerless in the default catalog would need issues turned on in the GitHub copy. That is a separate decision.

## cody, 2026-11-17T13:40:54-08:00

Merged in #210 at 32f4b8a. Marketplace repository validation and hassfest both passed. The issue-tracker validation is skipped because the read-only GitHub mirror has Issues disabled.
