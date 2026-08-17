#!/usr/bin/env bash
# Refuse to cut a release until the GitHub mirror's checks are green on the commit
# the release is cut FROM. (Not the tagged commit: the tag job stamps version
# strings and commits, and for a prerelease that child is never pushed to a
# branch, so no branch workflow can evaluate it. The caller's intent check
# constrains the delta to version files.)
#   check-mirror-ci.sh <sha> [workflow-name]
#
# Forgejo has no macOS runner, so the only thing that ever builds the Homebrew
# formula on a Mac is `CI (macOS)` on the mirror. Without this the release gate
# is blind to it — which is how a release candidate shipped whose every
# brew-installed command died on `ImportError: ... mis-aligned LINKEDIT string
# pool`, a macOS-only corruption of cryptography's Rust extension. The Linux
# smoke passed the whole time, because a Linux container cannot see it.
#
# Deliberately UNAUTHENTICATED: the gate job holds no credential by design (only
# the tag job is handed a write token), and the mirror is public. Unauthenticated
# GitHub allows 60 requests/hour per IP, and this polls once a minute at most.
#
# Waits rather than failing fast, because the push-mirror is asynchronous: a
# release dispatched moments after a push will find no run at all for a while.
set -euo pipefail

sha="${1:?usage: check-mirror-ci.sh <sha> [workflow-name]}"
want="${2:-CI (macOS)}"
repo="${MIRROR_REPO:-SisyphusMD/whiskerless}"
timeout="${MIRROR_CI_TIMEOUT:-2400}"
interval="${MIRROR_CI_INTERVAL:-60}"

api="https://api.github.com/repos/${repo}/actions/runs?head_sha=${sha}&per_page=50"
deadline=$(( $(date +%s) + timeout ))

echo "Waiting for '${want}' on ${repo}@${sha:0:12} (up to $(( timeout / 60 )) min)"

runs_json="$(mktemp)"
trap 'rm -f "$runs_json"' EXIT

while :; do
  fetched=false
  code="$(curl -sS -o "$runs_json" -w '%{http_code}' \
    -H 'Accept: application/vnd.github+json' "$api" || echo 000)"
  case "$code" in
    200) fetched=true ;;
    403|429)
      # Rate limited or throttled. Not a verdict on the commit, so keep waiting
      # rather than failing a release for somebody else's traffic on this IP.
      echo "  GitHub returned ${code} (rate limit?) — retrying"
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
    echo "::error::timed out waiting for '${want}' on ${repo}@${sha:0:12}" >&2
    echo "Either the push-mirror has not delivered this commit, or the run is stuck." >&2
    echo "Check https://github.com/${repo}/actions and dispatch again once it is green." >&2
    exit 1
  fi
  sleep "$interval"
done
