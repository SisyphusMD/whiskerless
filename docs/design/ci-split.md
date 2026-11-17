# Which forge runs what

**Architecture picks the runner, and nothing is emulated.** Build, test and release jobs run on
Forgejo, on a runner that is natively the architecture it tests: `ubuntu-latest`
for Linux amd64, `ubuntu-26.04-arm` for Linux arm64, and `macos-15-vm` /
`macos-27-vm` for the macOS floor and current macOS. GitHub runs the mirror lockdown workflow.
The `test_only_mirror_lockdown_runs_on_github` invariant checks the workflow directory.

Forgejo (`forgejo.bryantserver.com`) is the primary repo and its runners are ours.
GitHub is a read-only mirror that HACS installs from, and one of the three
registries every release is uploaded to. Its runners were used because Apple
notarizes only from a Mac and nobody here had arm64 hardware; both now exist here.

## What the runners actually are

Worth stating plainly, because a comment in `bottles.yml` claimed the opposite for
months and would have sent anyone reading it to the wrong forge:

| | Runner |
|---|---|
| Linux x86_64 | `ubuntu-latest`, natively |
| Linux arm64 | `ubuntu-26.04-arm`, natively |
| macOS | macOS 15 and the newest macOS (`macos-15-vm`, `macos-27-vm`) |

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

## Adding a job

Ask what hardware it needs, then put it in `.forgejo/workflows/` on that runner.
`.github/workflows/` holds the mirror lockdown workflow.

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

## One matrix, three platforms

`install-matrix.yml` runs every Linux channel on amd64 and on arm64, and the `.pkg`,
bottle pour and PyPI-via-uvx channels on both macOS VMs, in one run the gate reads
once. Both Linux legs call `packaging/install-matrix-arch.sh`, which owns the channel
list, so the two architectures cannot test different sets; an invariant test pins
that they both call it.
