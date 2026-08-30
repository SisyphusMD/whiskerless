#!/usr/bin/env bash
# Wait for one GitHub-mirror workflow to reach a verdict on one exact commit.
#   check-mirror-ci.sh <sha> <workflow-file>
#
# e.g. check-mirror-ci.sh "$SHA" .github/workflows/ci-macos.yml
#
# Forgejo has no macOS runner, so anything built on a Mac is built only on the mirror. Without a
# gate like this the release path is blind to it — which is how a release candidate shipped whose
# every brew-installed command died on `ImportError: ... mis-aligned LINKEDIT string pool`, a
# macOS-only corruption of cryptography's Rust extension. The Linux smoke passed the whole time,
# because a Linux container cannot see it.
#
# The workflow is named by FILE, never by display name: a display name is prose that gets reworded,
# and a reworded one would match no runs at all — which this reads as "not delivered yet" and turns
# into a timeout blaming the mirror. The path survives renaming the workflow's `name:`.
#
# MIRROR_CI_TOKEN is REQUIRED. Unauthenticated github.com allows 60 requests an hour per IP and
# every runner and mirror probe shares one, so the unauthenticated path answered 403 rather than
# answering the question. Requiring it costs nothing that mattered: the token is read-only and
# needs no scopes at all for a public repository, so it is not the WRITE credential this job
# still deliberately does not hold.
#
# Waits rather than failing fast, because the push-mirror is asynchronous: a release dispatched
# moments after a push will find no run at all for a while.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"

sha="${1:?usage: check-mirror-ci.sh <sha> <workflow-file>}"
workflow="${2:?usage: check-mirror-ci.sh <sha> <workflow-file>}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid commit SHA: $sha" >&2; exit 2; }
repo="${MIRROR_REPO:-$PROJECT_REPO_SLUG}"
timeout="${MIRROR_CI_TIMEOUT:-2400}"
# Sized to the authenticated ceiling of 5,000/hour, which is the only one that now applies.
# 30s costs ~120 requests an hour, under 3% of that quota, and a slower interval would only add
# rounding: the verdict is noticed at the next boundary, so a run finishing at 23:54 read every
# 300s is reported at 23:56 and the release waits out the difference for nothing.
: "${MIRROR_CI_TOKEN:?a read-only GitHub token is required; this must never poll GitHub unauthenticated}"
poll_interval="${MIRROR_CI_INTERVAL:-30}"
interval="$poll_interval"

# event=push, not every run for the sha. A pull_request run for the same commit is evidence about
# the PR, not about the branch the release is cut from — and because a success below outranks a
# failure, counting one would let a green PR run mask a failing push run.
api="https://api.github.com/repos/${repo}/actions/runs?event=push&head_sha=${sha}&per_page=50"
deadline=$(( $(date +%s) + timeout ))
throttled=0

echo "Waiting for '${workflow}' on ${repo}@${sha:0:12} (up to $(( timeout / 60 )) min)"

runs_json="$(mktemp)"
headers="$(mktemp)"
trap 'rm -f "$runs_json" "$headers"' EXIT

while :; do
  fetched=false
  auth=(-H "Authorization: Bearer ${MIRROR_CI_TOKEN}")
  code="$(curl -sS -o "$runs_json" -D "$headers" -w '%{http_code}' \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' "${auth[@]}" "$api" || echo 000)"
  case "$code" in
    200)
      fetched=true
      # Clear the throttle record: a successful read means the eventual timeout
      # is about the RUN, not the quota, and the diagnosis must say so.
      throttled=0
      interval="$poll_interval"
      ;;
    403|429)
      # Rate limited or throttled. Not a verdict on the commit, so keep waiting
      # rather than failing a release for somebody else's traffic on this IP —
      # but back off hard, because hammering a rate limit only extends it.
      throttled=$(( throttled + 1 ))
      # GitHub states exactly when the quota returns. Waiting for that beats
      # doubling blindly, which either hammers the limit or overshoots it.
      reset="$(awk -F': *' 'tolower($1)=="x-ratelimit-reset"{gsub(/\r/,"",$2); print $2}' "$headers")"
      now="$(date +%s)"
      if [ -n "$reset" ] && [ "$reset" -gt "$now" ] 2>/dev/null; then
        interval=$(( reset - now + 5 ))
        echo "  GitHub returned ${code} (rate limited) — quota resets in ${interval}s, waiting for it"
        # The reset can be up to an hour away; a deadline shorter than that would
        # fail a release over a quota rather than over the code.
        [ $(( now + interval + 60 )) -gt "$deadline" ] && deadline=$(( now + interval + 60 ))
      else
        interval=$(( interval * 2 ))
        [ "$interval" -gt 900 ] && interval=900
        echo "  GitHub returned ${code} (rate limited) — backing off to ${interval}s"
      fi
      ;;
    401)
      # An expired or revoked token. Retrying cannot fix it, and letting it fall
      # through would spend the whole timeout and then blame the run — sending
      # somebody to read CI logs when the answer is a dead credential.
      echo "::error::GitHub rejected the credential (401). MIRROR_CI_TOKEN is expired, revoked or malformed." >&2
      echo "Rotate MIRROR_CI_TOKEN. Removing it is not an option: an unauthenticated poll gets 60 requests an hour per IP, shared by every runner, so it answers 403 instead of answering." >&2
      exit 1
      ;;
    *) echo "  GitHub returned ${code} — retrying" ;;
  esac

  if [ "$fetched" = true ]; then
    # Heredoc for the parser, JSON via a file: the alternative is escaped quotes
    # inside a quoted shell string, which is how the first version of this
    # silently returned "unreadable" on every poll and could only ever time out.
    verdict="$(python3 - "$sha" "$workflow" "$runs_json" <<'PY' || echo "PENDING unreadable"
import json, sys

sha, workflow, path = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    runs = json.load(handle).get("workflow_runs", [])

# `path` carries the ref for a run dispatched from another branch
# (`.github/workflows/ci-macos.yml@refs/heads/x`), so compare only the file part.
matches = [
    r for r in runs
    if r.get("head_sha") == sha and r.get("path", "").split("@", 1)[0] == workflow
]

# A success is positive evidence that this commit builds; a cancelled or superseded sibling run
# adds nothing to it. Requiring EVERY run to be green instead means one cancelled re-run blocks a
# release, which is a verdict about scheduling rather than about the code.
#
# `success` and nothing else. A run whose jobs were all skipped concludes "skipped" having proven
# nothing, and under a first-success-wins rule that one run would authorize the release by itself —
# so a regression in a job-level `if` would read as a green macOS build. If a workflow ever does
# skip legitimately on a push, this waits and then times out, which is visible and fixable; a
# false PASS is neither.
run = next((r for r in matches if r.get("status") == "completed"
            and r.get("conclusion") == "success"), None)
if run:
    print("PASS " + str(run.get("html_url")))
elif not matches:
    print("PENDING none yet")
elif any(r.get("status") != "completed" for r in matches):
    print("PENDING still running")
else:
    print("FAIL " + ", ".join(
        str(r.get("conclusion")) + " " + str(r.get("html_url")) for r in matches))
PY
)"

    case "$verdict" in
      PASS*)
        echo "  ${workflow} is green on ${sha:0:12} (${verdict#PASS })"
        exit 0
        ;;
      FAIL*)
        echo "::error::${workflow} is NOT green on ${sha:0:12}: ${verdict#FAIL }" >&2
        echo "This workflow runs only on the mirror. Fix it, push, and dispatch again." >&2
        exit 1
        ;;
      *) echo "  ${verdict#PENDING } — waiting" ;;
    esac
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    if [ "$throttled" -gt 0 ]; then
      # Do not let a rate limit masquerade as a broken build: the difference
      # decides whether somebody goes looking at their code or at their quota.
      echo "::error::gave up waiting for '${workflow}' on ${repo}@${sha:0:12} — GitHub rate-limited ${throttled} of the polls, so this is NOT a verdict on the commit" >&2
      echo "MIRROR_CI_TOKEN is already required, so this is the AUTHENTICATED 5,000/hour quota, not the 60/hour one: something else is spending it against the same token or IP." >&2
      exit 1
    fi
    echo "::error::timed out waiting for '${workflow}' on ${repo}@${sha:0:12}" >&2
    echo "Either the push-mirror has not delivered this commit, or the run is stuck." >&2
    echo "Check https://github.com/${repo}/actions and dispatch again once it is green." >&2
    exit 1
  fi
  sleep "$interval"
done
