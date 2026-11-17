# #207 Trust gate: name fork PRs in CONTRIBUTING, and fix the stale install-matrix line

- Kind: issue, state: closed, by cody, created 2026-11-17T13:11:49-08:00
- Labels: none; milestone: none

Follow-up to the AGit gate (`github.event.pull_request.flow == 0` beside the head-repository check) and SisyphusMD/project-rules#79.

- The trust-gate test already checks every job of a `pull_request` workflow against a named exemption map (empty here), so a job that loses its whole `if:` fails it. Nothing to change there.
- `CONTRIBUTING.md` says an AGit pull request gets no CI. It should say the same of a pull request from a fork, and that a maintainer re-pushes the change to a branch here to run CI.
- The "What that does not cover" install-matrix bullet still uses the old "here" versus "on Forgejo" framing from when CI ran on GitHub. Correct it.

## cody, 2026-11-17T13:40:53-08:00

Merged in #210 at 32f4b8a. The guard tests passed and the workflow and contributor guide now describe the AGit and fork gate.
