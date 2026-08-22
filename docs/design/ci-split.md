# Which forge runs what

**Architecture decides the forge, and nothing is emulated.** Everything that can
run natively on our own hardware runs on Forgejo; macOS and arm64 run on GitHub,
because that is where the native machines are.

That is the rule, and it is enforced by
`tests/test_repo_invariants.py::test_github_only_runs_what_only_github_can_run`
rather than by memory — a job added to `.github/workflows/` on a runner that is
neither macOS nor arm64 fails the suite unless it is listed as an exception with
its reason.

Forgejo (`forgejo.bryantserver.com`) is the primary repo and its runners are ours.
GitHub is a read-only mirror that exists because HACS installs from it, because
Apple will not let anyone else notarize, because nobody here has arm64 hardware,
and because a handful of things are welded to the GitHub ecosystem.

## What the runners actually are

Worth stating plainly, because a comment in `bottles.yml` claimed the opposite for
months and would have sent anyone reading it to the wrong forge:

| | Forgejo | GitHub |
|---|---|---|
| Linux x86_64 | **yes**, natively (Talos nodes) | yes |
| Linux arm64 | **no** — all seven nodes are amd64 | **yes**, natively (`ubuntu-24.04-arm`) |
| macOS | none | yes |

## Why no emulation

Cross-architecture work used to go through `docker buildx`, whose builder carries
its own QEMU, because that was the only arm64 available. It worked until it did
not: BuildKit runs an emulated guest binary through an injected emulator, so a
PyInstaller onefile app's parent process is `/dev/.buildkit_qemu_emulator` rather
than the app itself. PyInstaller 6.22.1 added a parent-executable check
(GHSA-9fxf-4qw3-ghmr) and every emulated arm64 self-test and package smoke began
failing. It cost this project's rc.18 Linux assets and the sibling's rc.13.

The deeper problem is what an emulated pass actually proves. A green arm64 leg
under qemu-user is a statement about qemu-user. The failure above is the case
where that gap was loud; the ones to worry about are the quiet ones.

So: arm64 builds, arm64 packaging and arm64 install tests all run on
`ubuntu-24.04-arm`, and the scripts refuse to proceed when the host architecture
and the target disagree — `packaging/build-linux-arch.sh` and
`packaging/install-matrix-arch.sh` both check, rather than trusting the workflow
to have sent them to the right runner.

## One property of the Forgejo runner still shapes its jobs

**The job itself runs in a container.** A bind mount of the workspace is invisible
to the daemon, and a port published with `docker run -p` is not reachable from the
job. buildx dodges both: its context and output are client-side streams.

So a Linux job for Forgejo is written as a Dockerfile with a `--target` per case
and `--output type=local` for its result, not as `docker run -v`. That is what
`packaging/package-smoke.Dockerfile` and `packaging/install-smoke.Dockerfile` are.
`--platform` still appears in those calls, but it now names the architecture the
runner already is; it is not a request to emulate.

## What legitimately lives on GitHub

Each of these is in the test's exception list, with the same reason recorded there:

- **macOS anything** — `ci-macos.yml`, `formula-macos.yml`, `release-macos.yml`,
  and the macOS legs of `install-matrix.yml`. Forgejo has no macOS runner, and the
  `.pkg` must be signed and notarized on a Mac.
- **arm64 anything** — `release-linux-arm64.yml`, and the `linux-arm64` leg of
  `install-matrix.yml`. No arm64 hardware here, and the alternative is the
  emulation described above.
- **`hassfest.yml`** — a GitHub-ecosystem action the Forgejo runner cannot fetch;
  it resolves actions from `data.forgejo.org`, which does not carry
  `home-assistant/actions`.
- **`ci-pr.yml`** — pull requests are on GitHub by project policy, so Forgejo
  never sees the event.
- **`retry-infra-failures.yml`** — it re-runs GitHub workflow runs through the
  GitHub API. There is nothing for it to do anywhere else.
- **`bottles.yml`** — the one genuine judgement call, and the one place the rule
  is bent. Three of its four tags need macOS or native arm64 anyway. The fourth,
  `x86_64_linux`, could run on Forgejo, but the four manifests must agree on
  `cellar` — `bottle-block.py` refuses a set that does not — and one matrix in one
  run is how that stays true. Splitting that leg across forges would mean
  collecting manifests across forges too, for one leg's worth of purity.
- **The coordinating jobs of `install-matrix.yml`** (`wait`, `summary`) — they
  exist to sequence and report the legs that must run on this forge.

## Adding a job

Ask what hardware it needs. Native amd64 Linux goes in `.forgejo/workflows/`.
macOS or arm64 goes in `.github/workflows/`. Anything else that genuinely cannot
run on Forgejo goes there too, with an entry in the invariant test's exception
list and the reason — the reason is the point, and an entry without one is the
failure this rule exists to prevent.

GitHub-only jobs carry `if: ${{ github.server_url == 'https://github.com' }}`.
Keep it. This instance records no runs at all for `.github/workflows/` — every run
in the repository's history comes from `.forgejo/workflows/` — but the guard costs
nothing and is what makes a workflow safe to read from either side, including one
whose actions Forgejo could not resolve.

## How the gate finds a matrix run

`check-rc-install-matrix.sh` requires BOTH halves to be green before a candidate
can be promoted, and each forge records "which tag did this test" differently:

- **GitHub** — a tag push sets `head_branch`; a re-dispatch (from main, on purpose,
  so a fix to the scripts is what re-runs) records the tag in the **run-name**.
  Hence `run-name: Install matrix (macOS + Linux arm64) …`.
- **Forgejo** — a tag push sets `prettyref`. Forgejo **ignores `run-name`**: a
  dispatched run's title is just the workflow `name:`, and a tag push's is the
  commit message, so neither says which tag was tested. It does evaluate **job**
  names, so the tag lives in the `wait` job's name and the gate reads
  `runs/{id}/jobs` to recognise a re-dispatch.

Both matrices are called `install-matrix.yml` and Forgejo reports the bare
filename as `workflow_id`, so the two lookups would collide if either forge listed
the other's runs. Neither does: each API returns only its own instance's runs, and
this instance records none for `.github/workflows/` at all.

## The two halves

| | Forgejo `install-matrix.yml` | GitHub `install-matrix.yml` |
|---|---|---|
| name | Install matrix (Linux amd64) | Install matrix (macOS + Linux arm64) |
| Linux channels | every one, on amd64 | every one, on arm64 |
| macOS channels | none | `.pkg`, bottle pour, PyPI via uvx |

Both Linux halves call `packaging/install-matrix-arch.sh`, which owns the channel
list. Two inline copies in two files on two forges is a divergence with a
schedule, and an invariant test pins that they both call it.
