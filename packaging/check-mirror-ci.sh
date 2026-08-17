#!/usr/bin/env bash
# Refuse to cut a release until the GitHub mirror's checks are green on the commit
# the release is cut FROM. (Not the tagged commit: the tag job stamps version
# strings and commits, and for a prerelease that child is never pushed to a
# branch, so no branch workflow can evaluate it. The caller's intent check
# constrains the delta to version files.)
#   check-mirror-ci.sh <sha> [workflow-name]
#
# Forgejo has no macOS runner, so the only thing that ever builds the Homebrew
# formula on a Mac is the `Homebrew formula (macOS)` workflow on the mirror —
# deliberately its own workflow, keyed per commit and never cancelled, because
# a cancelled run reads as not-green and a push during a release cut would
# otherwise kill the run the release is waiting on. Without this the release gate
# is blind to it — which is how a release candidate shipped whose every
# brew-installed command died on `ImportError: ... mis-aligned LINKEDIT string
# pool`, a macOS-only corruption of cryptography's Rust extension. The Linux
# smoke passed the whole time, because a Linux container cannot see it.
#
# Unauthenticated by default: the gate job holds no WRITE credential by design
# (only the tag job is handed one), and the mirror is public.
#
# But unauthenticated GitHub allows only 60 requests/hour PER IP, and the runner
# egresses from the same address as everything else on that network — so the
# budget is shared and can be exhausted by something else entirely. Observed
# 2026-08-17: a 403 on every poll, and the gate then timed out on a commit whose
# run had actually passed. Hence a slow interval, backoff on 403, and a message
# that names rate limiting instead of blaming the run.
#
# Set MIRROR_CI_TOKEN to a read-only GitHub token to get 5,000/hour instead. It
# needs no scopes at all for a public repository, so it stays far away from the
# write credential this job deliberately does not hold.
#
# Waits rather than failing fast, because the push-mirror is asynchronous: a
# release dispatched moments after a push will find no run at all for a while.
set -euo pipefail

sha="${1:?usage: check-mirror-ci.sh <sha> [workflow-name]}"
want="${2:-Homebrew formula (macOS)}"
repo="${MIRROR_REPO:-SisyphusMD/whiskerless}"
timeout="${MIRROR_CI_TIMEOUT:-2400}"
interval="${MIRROR_CI_INTERVAL:-300}"   # 300s: ~8 polls per 40 min, well under 60/hour

api="https://api.github.com/repos/${repo}/actions/runs?head_sha=${sha}&per_page=50"
deadline=$(( $(date +%s) + timeout ))
throttled=0

echo "Waiting for '${want}' on ${repo}@${sha:0:12} (up to $(( timeout / 60 )) min)"

runs_json="$(mktemp)"
headers="$(mktemp)"
trap 'rm -f "$runs_json" "$headers"' EXIT

while :; do
  fetched=false
  auth=()
  [ -n "${MIRROR_CI_TOKEN:-}" ] && auth=(-H "Authorization: Bearer ${MIRROR_CI_TOKEN}")
  code="$(curl -sS -o "$runs_json" -D "$headers" -w '%{http_code}' \
    -H 'Accept: application/vnd.github+json' "${auth[@]}" "$api" || echo 000)"
  case "$code" in
    200)
      fetched=true
      # Clear the throttle record: a successful read means the eventual timeout
      # is about the RUN, not the quota, and the diagnosis must say so.
      throttled=0
      interval="${MIRROR_CI_INTERVAL:-300}"
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
    *) echo "  GitHub returned ${code} — retrying" ;;
  esac

  if [ "$fetched" = true ]; then
    # Heredoc for the parser, JSON via a file: the alternative is escaped quotes
    # inside a quoted shell string, which is how the first version of this
    # silently returned "unreadable" on every poll and could only ever time out.
    verdict="$(python3 - "$want" "$runs_json" <<'PY' || echo "PENDING unreadable"
import json, sys

want, path = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    runs = [r for r in json.load(handle).get("workflow_runs", []) if r.get("name") == want]

if not runs:
    print("PENDING none yet")
elif any(r.get("status") != "completed" for r in runs):
    print("PENDING still running")
else:
    bad = [r for r in runs if r.get("conclusion") not in ("success", "skipped")]
    if bad:
        print("FAIL " + ", ".join(str(r.get("conclusion")) + " " + str(r.get("html_url")) for r in bad))
    else:
        print("PASS " + str(len(runs)) + " run(s)")
PY
)"

    case "$verdict" in
      PASS*)
        echo "  ${want} is green on ${sha:0:12} (${verdict#PASS })"
        exit 0
        ;;
      FAIL*)
        echo "::error::${want} is NOT green on ${sha:0:12}: ${verdict#FAIL }" >&2
        echo "The macOS Homebrew formula build lives only on the mirror. Fix it," >&2
        echo "push, and dispatch the release again." >&2
        exit 1
        ;;
      *) echo "  ${verdict#PENDING } — waiting" ;;
    esac
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    if [ "$throttled" -gt 0 ]; then
      # Do not let a rate limit masquerade as a broken build: the difference
      # decides whether somebody goes looking at their code or at their quota.
      echo "::error::gave up waiting for '${want}' on ${repo}@${sha:0:12} — GitHub rate-limited ${throttled} of the polls, so this is NOT a verdict on the commit" >&2
      echo "Set MIRROR_CI_TOKEN to a read-only GitHub token (no scopes needed for a public repo) to raise the limit from 60/hour to 5,000." >&2
      exit 1
    fi
    echo "::error::timed out waiting for '${want}' on ${repo}@${sha:0:12}" >&2
    echo "Either the push-mirror has not delivered this commit, or the run is stuck." >&2
    echo "Check https://github.com/${repo}/actions and dispatch again once it is green." >&2
    exit 1
  fi
  sleep "$interval"
done
