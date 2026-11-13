#!/usr/bin/env python3
"""Was a failed GitHub run the runner's fault, or ours?

    gh api --paginate "repos/$REPO/actions/runs/$RUN_ID/attempts/$ATTEMPT/jobs" > jobs.json
    gh api "repos/$REPO/actions/jobs/<id>/logs" > logs/<id>.log   # one per failed job
    gh api "repos/$REPO/check-runs/<id>/annotations" > annotations/<id>.json   # one per cancelled job
    ATTEMPT=<run attempt> triage-infra-failure.py jobs.json [logs/ [annotations/]] >> "$GITHUB_OUTPUT"

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

The third class is a runner whose ADDRESS is banned at Forgejo's edge (observed, dreame-valetudo
v0.3.0-rc.48): hosted runners borrow recycled cloud addresses, and one had been banned for an
exploit probe hours earlier, so every request it made got HTTP 403. A 403 is also what a revoked
token gets, so the status alone proves nothing. The proof is structural instead: every job that
reaches Forgejo first runs `forgejo-preflight.sh` as a step of its own, an anonymous read of a
public endpoint that Forgejo itself never refuses. Retried only when THAT step failed with THAT
script's marker; a 403 anywhere else stays ours.

The fourth class is a job no runner ever picked up (observed, whiskerless rc.74 and rc.75): when
GitHub's macOS arm64 pool is short, it cancels a queued job after fifteen minutes and says so in the
job's annotation, "The job was not acquired by Runner of type hosted even after multiple attempts".
The job is `cancelled`, not `failure`, so the first three rules never see it, and a cancel otherwise
vetoes the retry. The evidence is the annotation's exact spelling on a job that ran no step and was
assigned no runner; a cancel by a person, or by a concurrency group, carries neither. It is also the
one class that recurs: the pool stays short for hours, so one retry was not enough (one release
took six). Only a run whose every cause is this class is retried past the first attempt, up to
`MAX_CAPACITY_ATTEMPTS`; anything else still gets exactly one.

Shared between projects because none of this reasoning is project-specific. What IS project-specific
is which workflows to watch, and that stays in each repository's own workflow file.
"""

from __future__ import annotations

import json
import os
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

#: The step every Forgejo-reaching job runs first, and the exact line `forgejo-preflight.sh` prints
#: when the edge refused the runner. Both must match: the name pins the evidence to the one step whose
#: only request is anonymous, so an authenticated 403 later in the job can never borrow it.
PREFLIGHT_STEP = "Check this runner can reach Forgejo"
EDGE_BAN_SIGNATURE = "forgejo-preflight: edge refused this runner"

#: Steps whose only job is to restate other jobs' results, so they fail exactly when one of those
#: did: the install matrix's `Verdict` turns a leg's failure into a red summary. Such a step is
#: never evidence either way, because the jobs it restates are judged on their own; but it cannot
#: make a run retryable alone, or a leg a human cancelled would come back as a retry.
DERIVATIVE_STEPS = frozenset({"Verdict"})

#: Exactly what GitHub writes in the annotation of a job it gave up on queueing, and the attempt past
#: which even that stops being retried. The bound is what keeps a pool that is gone for the day from
#: retrying forever; past it the run stays red for a person to look at.
NOT_ACQUIRED_SIGNATURE = "was not acquired by Runner"
MAX_CAPACITY_ATTEMPTS = 5

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


def edge_ban(log: str, step: dict) -> bool:
    """Whether this is the preflight step, failing because the edge refused the runner's address.

    Reads the step's window INCLUDING both boundary seconds, unlike `_step_lines`: a refused probe
    finishes in milliseconds, so its whole output sits in the second it started or the next, and the
    exclusive window would never see it. Borrowing a neighbour's line is harmless here, because the
    marker is printed only by `forgejo-preflight.sh`, and that script runs only in this step."""
    if step.get("name") != PREFLIGHT_STEP:
        return False
    start, end = step.get("started_at"), step.get("completed_at")
    if not start or not end:
        return False
    start, end = start[:19], end[:19]
    window = [line for line in log.splitlines() if start <= line[:19] <= end]
    return EDGE_BAN_SIGNATURE in "\n".join(window[-TAIL_LINES:])


def never_acquired(job: dict, annotations: list[str]) -> bool:
    """Whether GitHub cancelled this job because no runner ever took it. All three must hold: no
    step ran, no runner was assigned, and GitHub's own annotation says so."""
    return (
        job.get("conclusion") == "cancelled"
        and not job.get("steps")
        and not job.get("runner_name")
        and any(NOT_ACQUIRED_SIGNATURE in message for message in annotations)
    )


def triage(
    jobs: list[dict],
    logs: dict[int, str] | None = None,
    annotations: dict[int, list[str]] | None = None,
    attempt: int = 1,
) -> tuple[bool, list[str]]:
    """(is_infra, human-readable report). Not infra when nothing failed or went unqueued: there is
    then nothing to explain and nothing to re-run. `logs` maps job id to that job's log text, and
    `annotations` to its annotation messages; a failure of ours with no log to read, or a cancel with
    no annotation to read, is treated as ours. `attempt` is the run attempt being judged."""
    failed = [j for j in jobs if j.get("conclusion") == "failure"]
    unqueued = [j for j in jobs if never_acquired(j, (annotations or {}).get(j.get("id"), []))]
    report = [f"{j['name']}: no runner ever took it (GitHub capacity); retryable" for j in unqueued]
    infra = bool(failed or unqueued)
    caused = bool(unqueued)
    # Whether anything besides a missing runner explains the run; a derivative summary does not.
    other_cause = False
    # A hang or any other cancel is nobody's evidence of a runner fault, and it is not in `failed`
    # to be judged, so it vetoes outright. Without this a timed-out leg would ride along on another
    # leg's retry once the summary that used to report it red is exempted as derivative.
    for job in jobs:
        if job in unqueued:
            continue
        if job.get("conclusion") in ("timed_out", "cancelled"):
            infra = False
            report.append(f"{job['name']}: {job['conclusion']}; not retrying")
    for job in failed:
        log = (logs or {}).get(job.get("id"), "")
        bad = [s for s in job.get("steps", []) if s.get("conclusion") == "failure"]
        report.append(f"{job['name']}: failed steps={[s['name'] for s in bad] or ['(none recorded)']}")
        if not bad:
            caused = other_cause = True
        for step in bad:
            if step["name"] in DERIVATIVE_STEPS:
                report.append(f"    -> {step['name']!r} only restates other jobs; judged by them")
                continue
            caused = other_cause = True
            if step["name"] in RUNNER_PHASES:
                continue
            if edge_ban(log, step):
                report.append(f"    -> {step['name']!r}: the edge refused this runner's address; retryable")
                continue
            signature = transient_network_failure(log, step)
            if signature:
                report.append(f"    -> {step['name']!r} hit a resolver failure ({signature!r}); retryable")
                continue
            infra = False
            report.append(f"    -> our step failed: {step['name']!r}; not retrying")
    if infra and caused and attempt > 1:
        # Every class but the capacity cancel is a one-off, so its second failure is not transient.
        if other_cause:
            report.append(f"attempt {attempt}: only a capacity cancel is retried past the first attempt")
            return False, report
        if attempt >= MAX_CAPACITY_ATTEMPTS:
            report.append(f"attempt {attempt}: no runner after {attempt} attempts; leaving it red")
            return False, report
    return infra and caused, report


def load_logs(directory: Path) -> dict[int, str]:
    """`<job id>.log` files, as the workflow downloads them. Anything unparseable is skipped rather
    than fatal: a missing log only makes that job's failure count as ours, which is the safe side."""
    logs: dict[int, str] = {}
    for path in directory.glob("*.log"):
        if path.stem.isdigit():
            logs[int(path.stem)] = path.read_text(errors="replace")
    return logs


def load_annotations(directory: Path) -> dict[int, list[str]]:
    """`<job id>.json` files, each the check-run annotations API's list. Anything unparseable is
    skipped, which makes that job's cancel count as ours: the safe side."""
    found: dict[int, list[str]] = {}
    for path in directory.glob("*.json"):
        if not path.stem.isdigit():
            continue
        try:
            items = json.loads(path.read_text(errors="replace"))
        except ValueError:
            continue
        if isinstance(items, list):
            found[int(path.stem)] = [str(i.get("message", "")) for i in items if isinstance(i, dict)]
    return found


def main() -> int:
    if len(sys.argv) not in (2, 3, 4):
        print(f"usage: {sys.argv[0]} <jobs.json> [logs-dir [annotations-dir]]", file=sys.stderr)
        return 2
    jobs = json.loads(Path(sys.argv[1]).read_text())["jobs"]
    logs = load_logs(Path(sys.argv[2])) if len(sys.argv) >= 3 else {}
    annotations = load_annotations(Path(sys.argv[3])) if len(sys.argv) == 4 else {}
    attempt = int(os.environ.get("ATTEMPT") or 1)
    infra, report = triage(jobs, logs, annotations, attempt)
    print(f"infra={'true' if infra else 'false'}")
    print("summary<<EOF")
    print("\n".join(report) or "no failed jobs found")
    print("EOF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
