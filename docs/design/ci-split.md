# Which forge runs what

**Architecture picks the runner, and nothing is emulated.** Every job belongs on
Forgejo, on a runner that is natively the architecture it tests: `ubuntu-latest`
for Linux amd64, `ubuntu-26.04-arm` for Linux arm64, and `macos-15-vm` /
`macos-27-vm` for the macOS floor and current macOS. A job still on GitHub is one
that has not moved yet.

`tests/test_repo_invariants.py::test_github_only_runs_what_only_github_can_run`
holds what is left on GitHub to that rule: a job in `.github/workflows/` on a
runner that is neither macOS nor arm64 fails the suite unless it is listed as an
exception with its reason.

Forgejo (`forgejo.bryantserver.com`) is the primary repo and its runners are ours.
GitHub is a read-only mirror that HACS installs from. Its runners were used
because Apple notarizes only from a Mac and nobody here had arm64 hardware; both
now exist here, and the release jobs still on GitHub are moving off it.

## What the runners actually are

Worth stating plainly, because a comment in `bottles.yml` claimed the opposite for
months and would have sent anyone reading it to the wrong forge:

| | Forgejo | GitHub |
|---|---|---|
| Linux x86_64 | **yes**, natively (`ubuntu-latest`) | yes |
| Linux arm64 | **yes**, natively (`ubuntu-26.04-arm`) | yes |
| macOS | **yes**: macOS 15 and the newest macOS (`macos-15-vm`, `macos-27-vm`) | yes |

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

So: arm64 builds, arm64 packaging and arm64 install tests all run on a native
arm64 runner, and the scripts refuse to proceed when the host architecture
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

- **The macOS release jobs** — `release-macos.yml` and the macOS legs of
  `install-matrix.yml`. They are here because they have not moved yet: the `.pkg`
  must be signed and notarized on a Mac, and the Macs here now run the tests and
  the formula smoke on every push (`macos.yml`, a required check). The release jobs
  move next.
- **arm64 anything** — `release-linux-arm64.yml`, and the `linux-arm64` leg of
  `install-matrix.yml`. There was no arm64 hardware here, and the alternative
  was the emulation described above. There is now: Forgejo builds and
  install-tests the same tags natively too (`release-arm64.yml`,
  `install-matrix-arm64.yml`), and these copies go once both agree.
- **`bottles.yml`** — the one genuine judgement call, and the one place the rule
  is bent. Two of its three tags need macOS or native arm64 anyway. The third,
  `x86_64_linux`, could run on Forgejo, but the run's append job uploads every
  leg's bottle and manifest from the artifacts of that same run, and artifacts are
  run-scoped. Splitting that leg across forges would mean collecting bottles and
  manifests across forges too, for one leg's worth of purity.
- **The coordinating jobs of `install-matrix.yml`** (`wait`, `summary`) — they
  exist to sequence and report the legs that must run on this forge.

## Adding a job

Ask what hardware it needs, then put it in `.forgejo/workflows/` on that runner.
Nothing new goes in `.github/workflows/`; the jobs there are release jobs that
have not moved yet.

GitHub-only jobs carry `if: ${{ github.server_url == 'https://github.com' }}`.
Keep it. This instance records no runs at all for `.github/workflows/` — every run
in the repository's history comes from `.forgejo/workflows/` — but the guard costs
nothing and is what makes a workflow safe to read from either side, including one
whose actions Forgejo could not resolve.

## How the gate finds a matrix run

`check-rc-install-matrix.sh` reads Forgejo only: every workflow named in
`INSTALL_MATRIX_WORKFLOWS` (default `install-matrix.yml`) must be green for the
candidate. A shadow matrix, which swallows its own failures, is never listed, and
an invariant test holds that line.

- A tag push sets `prettyref`, so a run for the tag is recognised by its ref.
- Forgejo **ignores `run-name`**. A dispatched run's title is just the workflow
  `name:`, and a tag push's is the commit message, so neither says which tag was
  tested. It does evaluate **job** names, so the tag lives in the `wait` job's name
  and the gate reads `runs/{id}/jobs` to recognise a re-dispatch (which runs from
  main, on purpose, so a fix to the scripts is what re-runs).

While the macOS and arm64 install legs still run in GitHub's `install-matrix.yml`,
this gate cannot see them. So `release.yml` refuses a stable cut for as long as that
file exists, and the refusal clears once it is gone.

## The two halves

| | Forgejo `install-matrix.yml` | GitHub `install-matrix.yml` |
|---|---|---|
| name | Install matrix (Linux amd64) | Install matrix (macOS + Linux arm64) |
| Linux channels | every one, on amd64 | every one, on arm64 |
| macOS channels | none | `.pkg`, bottle pour, PyPI via uvx |

Both Linux halves call `packaging/install-matrix-arch.sh`, which owns the channel
list. Two inline copies in two files on two forges is a divergence with a
schedule, and an invariant test pins that they both call it.
