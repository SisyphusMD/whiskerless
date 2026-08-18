# Which forge runs what

**Forgejo runs everything. GitHub runs only what cannot run anywhere else.**

That is the rule, and it is enforced by
`tests/test_repo_invariants.py::test_github_only_runs_what_only_github_can_run`
rather than by memory — a job added to `.github/workflows/` on a Linux runner
fails the suite unless it is listed as an exception with its reason.

Forgejo (`forgejo.bryantserver.com`) is the primary repo and its runners are ours.
GitHub is a read-only mirror that exists because HACS installs from it, because
Apple will not let anyone else notarize, and because a handful of things are
welded to the GitHub ecosystem.

## What the runners actually are

Worth stating plainly, because a comment in `bottles.yml` claimed the opposite for
months and would have sent anyone reading it to the wrong forge:

| | Forgejo | GitHub |
|---|---|---|
| Linux x86_64 | **yes**, natively (Talos nodes) | yes |
| Linux arm64 | **emulated only** — buildx carries QEMU; a plain `docker run --platform arm64` gets `exec format error` | yes, natively (`ubuntu-24.04-arm`) |
| macOS | none | yes |

Two properties of the Forgejo runner shape everything written for it, and both
are already worked around in `publish.yml`:

- **No host binfmt.** Cross-architecture work goes through `docker buildx`, whose
  builder carries its own QEMU. `docker run --platform linux/arm64` does not work.
- **The job itself runs in a container.** A bind mount of the workspace is
  invisible to the daemon, and a port published with `docker run -p` is not
  reachable from the job. buildx dodges both: its context and output are
  client-side streams.

So a Linux job for Forgejo is written as a Dockerfile with a `--target` per case
and `--output type=local` for its result, not as `docker run -v`. That is what
`packaging/package-smoke.Dockerfile` and `packaging/install-smoke.Dockerfile` are.

## What legitimately lives on GitHub

Each of these is in the test's exception list, with the same reason recorded there:

- **macOS anything** — `ci-macos.yml`, `formula-macos.yml`, `release-macos.yml`,
  and the macOS half of `install-matrix.yml`. Forgejo has no macOS runner, and the
  `.pkg` must be signed and notarized on a Mac.
- **`hassfest.yml`** — a GitHub-ecosystem action the Forgejo runner cannot fetch;
  it resolves actions from `data.forgejo.org`, which does not carry
  `home-assistant/actions`.
- **`ci-pr.yml`** — pull requests are on GitHub by project policy, so Forgejo
  never sees the event.
- **`retry-infra-failures.yml`** — it re-runs GitHub workflow runs through the
  GitHub API. There is nothing for it to do anywhere else.
- **`bottles.yml`** — the one genuine judgement call. `arm64_linux` has no native
  arm64 runner here, and a bottle is produced by a *from-source* build (that is
  the entire point of shipping one), measured at ~18 minutes natively, so
  emulating it is not a trade worth making. The other three are built beside it
  because the four manifests must agree on `cellar` — `bottle-block.py` refuses a
  set that does not — and one matrix on one forge is how that stays true.
- **The coordinating jobs of `install-matrix.yml`** (`wait`, `summary`) — they
  exist to sequence and report the macOS legs on this forge.

## Adding a job

Ask whether it *cannot* run on Forgejo. If it can, it goes in
`.forgejo/workflows/`. If it genuinely cannot, put it in `.github/workflows/` and
add it to the exception list in the invariant test with the reason — the reason is
the point, and an entry without one is the failure this rule exists to prevent.

GitHub-only jobs carry `if: ${{ github.server_url == 'https://github.com' }}`.
Keep it. This instance records no runs at all for `.github/workflows/` — every run
in the repository's history comes from `.forgejo/workflows/` — but the guard costs
nothing and is what makes a workflow safe to read from either side, including one
whose actions Forgejo could not resolve.

The two install matrices share the filename `install-matrix.yml`, and Forgejo's
API reports the BARE filename as `workflow_id`. `check-rc-install-matrix.sh`
therefore also matches on the run-name, which is why each half's `run-name:` names
its own platform.
