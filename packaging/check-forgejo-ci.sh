#!/usr/bin/env bash
# Wait for one Forgejo workflow to reach a verdict on one exact commit.
#   check-forgejo-ci.sh <sha> <workflow-file>
#
# e.g. check-forgejo-ci.sh "$SHA" macos.yml
#
# The release gates use this to refuse a commit whose macOS run is not green: the release jobs
# never run the macOS suite themselves, so without it a commit that only breaks on a Mac would
# ship. That has happened: a candidate shipped whose every brew-installed command died on a
# macOS-only corruption of cryptography's Rust extension, while the Linux smoke stayed green.
#
# The workflow is named by FILE (Forgejo's workflow_id), never by display name: a display name is
# prose that gets reworded, and a reworded one would match no runs at all, which this would read as
# "not started yet" and turn into a timeout.
#
# FORGEJO_CI_TOKEN is optional: the projects are public and Forgejo reads them without one. A
# workflow passes its own job token so that a private repository works the same way.
#
# Waits rather than failing fast: a release dispatched moments after a push finds the run still
# queued, or not created yet.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"

sha="${1:?usage: check-forgejo-ci.sh <sha> <workflow-file>}"
workflow="${2:?usage: check-forgejo-ci.sh <sha> <workflow-file>}"
# Both are interpolated into a URL, so a malformed one is refused before it is ever sent.
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid commit SHA: $sha" >&2; exit 2; }
[[ "$workflow" =~ ^[A-Za-z0-9._-]+\.ya?ml$ ]] || {
  echo "invalid workflow file: $workflow (the file name, e.g. macos.yml)" >&2; exit 2; }
repo="${FORGEJO_CI_REPO:-$PROJECT_REPO_SLUG}"
server="${FORGEJO_CI_SERVER:-${GITHUB_SERVER_URL:-https://forgejo.bryantserver.com}}"
timeout="${FORGEJO_CI_TIMEOUT:-2400}"
interval="${FORGEJO_CI_INTERVAL:-30}"

api="${server}/api/v1/repos/${repo}/actions/runs?workflow_id=${workflow}&head_sha=${sha}&limit=50"
auth=()
[ -z "${FORGEJO_CI_TOKEN:-}" ] || auth=(-H "Authorization: token ${FORGEJO_CI_TOKEN}")
deadline=$(( $(date +%s) + timeout ))

echo "Waiting for '${workflow}' on ${repo}@${sha:0:12} (up to $(( timeout / 60 )) min)"

runs_json="$(mktemp)"
jobs_json="$(mktemp)"
trap 'rm -f "$runs_json" "$jobs_json"' EXIT

# Prints CANDIDATES <yes|no: any still running> <ids of runs that concluded "success">,
# PENDING <why>, or FAIL <runs>.
classify_runs() {
  python3 - "$sha" "$workflow" "$runs_json" <<'PY' || echo "PENDING unreadable"
import json, sys

sha, workflow, path = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    runs = json.load(handle).get("workflow_runs") or []

# Filtered again here: the server's filter is a convenience, not something to trust a release on.
matches = [r for r in runs if r.get("commit_sha") == sha and r.get("workflow_id") == workflow]
done = {"success", "failure", "cancelled", "skipped"}
running = any(r.get("status") not in done for r in matches)
ok = [str(r.get("id")) for r in matches if r.get("status") == "success"]
if ok:
    print("CANDIDATES " + ("yes" if running else "no") + " " + " ".join(ok))
elif not matches:
    print("PENDING none yet")
elif running:
    print("PENDING still running")
else:
    # "skipped" is not a pass: a run that skipped every job proved nothing about the commit.
    print("FAIL " + ", ".join(str(r.get("status")) + " " + str(r.get("html_url")) for r in matches))
PY
}

while :; do
  code="$(curl -sS -o "$runs_json" -w '%{http_code}' "${auth[@]}" "$api" || echo 000)"
  case "$code" in
    200)
      verdict="$(classify_runs)"
      # A run that concluded "success" is only a candidate: a run whose macOS jobs were all
      # skipped (macos-scope.sh scoping out a Renovate branch) also concludes "success", and it
      # tested nothing. So it passes only if EVERY job in it succeeded.
      if [ "${verdict%% *}" = CANDIDATES ]; then
        read -r _ verdict_running verdict_ids <<<"$verdict"
        verdict="FAIL"
        for id in ${verdict_ids}; do
          jcode="$(curl -sS -o "$jobs_json" -w '%{http_code}' "${auth[@]}" \
            "${server}/api/v1/repos/${repo}/actions/runs/${id}/jobs" || echo 000)"
          if [ "$jcode" != 200 ]; then verdict="PENDING jobs of run ${id} unreadable"; break; fi
          jobs_verdict="$(python3 - "$jobs_json" <<'PY' || echo "unreadable"
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    jobs = json.load(handle)
jobs = jobs.get("jobs", []) if isinstance(jobs, dict) else jobs
if jobs and all(j.get("status") == "success" for j in jobs):
    print("ok")
else:
    print(",".join(f"{j.get('name')}={j.get('status')}" for j in jobs) or "no jobs")
PY
)"
          if [ "$jobs_verdict" = ok ]; then verdict="PASS run ${id}"; break; fi
          if [ "$jobs_verdict" = unreadable ]; then verdict="PENDING jobs of run ${id} unreadable"; break; fi
          verdict="${verdict} run ${id} (${jobs_verdict})"
        done
        # A still-running sibling may yet pass; only a settled set is a verdict.
        if [ "${verdict%% *}" = FAIL ] && [ "$verdict_running" = yes ]; then verdict="PENDING still running"; fi
      fi
      case "$verdict" in
        PASS*)
          echo "  ${workflow} is green on ${sha:0:12} (${verdict#PASS })"
          exit 0
          ;;
        FAIL*)
          echo "::error::${workflow} is NOT green on ${sha:0:12}: ${verdict#FAIL }" >&2
          echo "Fix it, push, and dispatch again; or rerun it if the failure was the runner's." >&2
          exit 1
          ;;
        *) echo "  ${verdict#PENDING } — waiting" ;;
      esac
      ;;
    401|403)
      # Not something waiting fixes, so say so now instead of spending the timeout.
      echo "::error::Forgejo refused the read (${code}): FORGEJO_CI_TOKEN cannot read ${repo}'s runs" >&2
      exit 1
      ;;
    *) echo "  Forgejo returned ${code} — retrying" ;;
  esac

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "::error::timed out waiting for '${workflow}' on ${repo}@${sha:0:12}" >&2
    echo "The run is queued behind others, stuck, or was never created for this commit." >&2
    echo "Check ${server}/${repo}/actions and dispatch again once it is green." >&2
    exit 1
  fi
  sleep "$interval"
done
