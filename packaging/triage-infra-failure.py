#!/usr/bin/env python3
"""Was a failed GitHub run the runner's fault, or ours?

    gh api --paginate "repos/$REPO/actions/runs/$RUN_ID/attempts/$ATTEMPT/jobs" > jobs.json
    triage-infra-failure.py jobs.json >> "$GITHUB_OUTPUT"

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


def triage(jobs: list[dict]) -> tuple[bool, list[str]]:
    """(is_infra, human-readable report). Not infra when there are no failed jobs at all: there is
    then nothing to explain and nothing to re-run."""
    failed = [j for j in jobs if j.get("conclusion") == "failure"]
    report: list[str] = []
    infra = bool(failed)
    for job in failed:
        bad = [s["name"] for s in job.get("steps", []) if s.get("conclusion") == "failure"]
        ours = [name for name in bad if name not in RUNNER_PHASES]
        report.append(f"{job['name']}: failed steps={bad or ['(none recorded)']}")
        if ours:
            infra = False
            report.append(f"    -> our step failed: {ours}; not retrying")
    return infra, report


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <jobs.json>", file=sys.stderr)
        return 2
    jobs = json.loads(Path(sys.argv[1]).read_text())["jobs"]
    infra, report = triage(jobs)
    print(f"infra={'true' if infra else 'false'}")
    print("summary<<EOF")
    print("\n".join(report) or "no failed jobs found")
    print("EOF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
