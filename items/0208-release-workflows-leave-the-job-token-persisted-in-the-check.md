# #208 Release workflows leave the job token persisted in the checkout

- Kind: issue, state: closed, by cody, created 2026-11-17T13:11:50-08:00
- Labels: none; milestone: none

`publish.yml` and `prune-rcs.yml` check out the repository with the default `persist-credentials: true`, which leaves the job token in the workspace's git config for every later step, including third-party build and upload steps. None of these jobs uses it: the only pushes (the Homebrew tap jobs) go to a different repository with their own explicit credential.

Set `persist-credentials: false` on every checkout in both workflows, and extend the test that already holds the release workflows to this.

## cody, 2026-11-17T13:40:53-08:00

Merged in #210 at 32f4b8a. Release and prune checkouts release their checkout credentials. The checkout tests passed, and the next tag or dispatch will exercise the workflows.
