#!/usr/bin/env python3
"""Was a failed GitHub run the runner's fault, or ours?

    gh api --paginate "repos/$REPO/actions/runs/$RUN_ID/attempts/$ATTEMPT/jobs" > jobs.json
    gh api "repos/$REPO/actions/jobs/<id>/logs" > logs/<id>.log   # one per failed job
    triage-infra-failure.py jobs.json [logs/] >> "$GITHUB_OUTPUT"

Writes `infra=true|false` and a `summary` heredoc, both as GitHub step outputs.

GitHub's hosted runners occasionally fail BEFORE any of our steps run — the observed case was
`Set up job` dying with "Failed to load actions/checkout/<sha>/action.yml", i.e. the runner fetched
a truncated action manifest. The same pinned SHA loaded fine on three other runners in the same
matrix, so nothing in the repository could have prevented it.

"Just re-run it" is not a policy: it puts a human in the loop for a machine fault, and it trains
people to re-run red builds without reading them. So the caller retries automatically — but ONLY
when the failure is provably not ours.

The discriminator is exact rather than heuristic. A runner-phase failure looks like this (observed,
run 31446127430):

    job: Test (arm64, current)  conclusion: failure
       1 failure  Set up job          <- the only step; none of ours ran

A real failure always fails one of OUR named steps, with `Set up job` green above it. So: infra
only when EVERY failed step belongs to a phase the runner owns. A failing test can never be
attributed to `Set up job`, which is what keeps this from becoming a way to launder flaky tests
into green builds.

The second class is a step of ours that failed because the RUNNER'S NETWORK did (observed, run
35055059591): `brew test` bootstrapped Homebrew's own Ruby harness and the runner could not resolve
rubygems.org. Nothing in the repository could have prevented that either, but it lands in one of our
named steps, so the step-name rule alone refuses it. For those, the discriminator reads the failed
job's log and retries only when the FAILED STEP'S CLOSING LINES carry one of a short list of exact
resolver-failure spellings AND name a host CI is known to reach. Bounded to the step's own
timestamps and to its tail, so a test that prints one of those strings as expected output cannot
make an unrelated failure look transient; bounded to known hosts, so a URL the repository itself
broke stays red. Both lists grow from observed cases only; a signature that could match a real
failure ("connection refused", any timeout) is deliberately absent, because a broker or a fixture
that failed to start produces those too.

Shared between projects because none of this reasoning is project-specific. What IS project-specific
is which workflows to watch, and that stays in each repository's own workflow file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Runner phases that happen BEFORE any of our steps. Deliberately not `Complete job`: that fails
#: after our steps have already uploaded artifacts, and artifacts are immutable within a run — so
#: re-running would fail on the duplicate name rather than repair anything. A `Complete job` failure
#: also means the work itself finished.
RUNNER_PHASES = frozenset({"Set up job", "Set up runner"})

#: Exact spellings of "the runner could not resolve a host", one per resolver in play: macOS libc
#: (Ruby, Python and curl all surface it), glibc, curl's own wording, and Ruby's exception class.
#: Each is a name-resolution failure specifically, which a repository cannot cause: nothing we run
#: takes the resolver down. Keep it that narrow.
TRANSIENT_NETWORK_SIGNATURES = (
    "nodename nor servname provided, or not known",
    "Temporary failure in name resolution",
    "Could not resolve host",
    "Socket::ResolutionError",
)

#: The hosts a CI step legitimately reaches, and which the signature must name. A resolver failure
#: for any other name is far more likely a URL the repository just changed — `curl: (6) Could not
#: resolve host: typo.invalid` is the same spelling — and re-running that would only fail again.
KNOWN_HOSTS = (
    "rubygems.org",
    "pypi.org",
    "files.pythonhosted.org",
    "github.com",
    "githubusercontent.com",
    "formulae.brew.sh",
    "ghcr.io",
)

#: How far back from the end of the failed step the evidence may sit. A resolver failure that took
#: the step down is what the failing tool prints on its way out; one printed pages earlier was
#: survived (a retried fetch, an offline-behaviour test's expected output) and says nothing about
#: why the step then failed.
TAIL_LINES = 40


def _step_lines(log: str, step: dict) -> list[str]:
    """The log lines that belong to one step, by the second-granularity timestamps GitHub records
    on both the step and every log line. The line format is `<ISO-8601 with 7 fractional digits>Z
    <text>`; the step's `started_at`/`completed_at` have no fraction, so both are compared on their
    first 19 characters. Both boundary seconds are EXCLUDED: the previous step ends and this one
    starts within the same second, so a line there could belong to either. A step with no
    timestamps (never started) owns no lines."""
    start, end = step.get("started_at"), step.get("completed_at")
    if not start or not end:
        return []
    start, end = start[:19], end[:19]
    return [line for line in log.splitlines() if start < line[:19] < end]


def transient_network_failure(log: str, step: dict) -> str | None:
    """The signature that makes this step's failure the runner's, or None. Both the signature and a
    known host have to appear in the step's closing lines."""
    tail = "\n".join(_step_lines(log, step)[-TAIL_LINES:])
    if not any(host in tail for host in KNOWN_HOSTS):
        return None
    return next((sig for sig in TRANSIENT_NETWORK_SIGNATURES if sig in tail), None)


def triage(jobs: list[dict], logs: dict[int, str] | None = None) -> tuple[bool, list[str]]:
    """(is_infra, human-readable report). Not infra when there are no failed jobs at all: there is
    then nothing to explain and nothing to re-run. `logs` maps job id to that job's log text; a
    failed step of ours with no log to read is treated as ours."""
    failed = [j for j in jobs if j.get("conclusion") == "failure"]
    report: list[str] = []
    infra = bool(failed)
    for job in failed:
        log = (logs or {}).get(job.get("id"), "")
        bad = [s for s in job.get("steps", []) if s.get("conclusion") == "failure"]
        report.append(f"{job['name']}: failed steps={[s['name'] for s in bad] or ['(none recorded)']}")
        for step in bad:
            if step["name"] in RUNNER_PHASES:
                continue
            signature = transient_network_failure(log, step)
            if signature:
                report.append(f"    -> {step['name']!r} hit a resolver failure ({signature!r}); retryable")
                continue
            infra = False
            report.append(f"    -> our step failed: {step['name']!r}; not retrying")
    return infra, report


def load_logs(directory: Path) -> dict[int, str]:
    """`<job id>.log` files, as the workflow downloads them. Anything unparseable is skipped rather
    than fatal: a missing log only makes that job's failure count as ours, which is the safe side."""
    logs: dict[int, str] = {}
    for path in directory.glob("*.log"):
        if path.stem.isdigit():
            logs[int(path.stem)] = path.read_text(errors="replace")
    return logs


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(f"usage: {sys.argv[0]} <jobs.json> [logs-dir]", file=sys.stderr)
        return 2
    jobs = json.loads(Path(sys.argv[1]).read_text())["jobs"]
    logs = load_logs(Path(sys.argv[2])) if len(sys.argv) == 3 else {}
    infra, report = triage(jobs, logs)
    print(f"infra={'true' if infra else 'false'}")
    print("summary<<EOF")
    print("\n".join(report) or "no failed jobs found")
    print("EOF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
