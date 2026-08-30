#!/usr/bin/env bash
# packaging/check-mirror-ci.sh against a stubbed GitHub, with no network.
#
# This gate decides whether a release may be cut, and every one of its interesting paths is a
# response nobody can reproduce on demand: a rate limit, a dead token, a mirror that has not
# delivered the commit yet, a cancelled run beside a successful one. Stubbing curl is the only way
# to reach them before they happen during a release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SHA=0123456789abcdef0123456789abcdef01234567
OTHER=89abcdef0123456789abcdef0123456789abcdef
WORKFLOW=.github/workflows/ci-macos.yml
export SHA OTHER WORKFLOW

# The real script asks curl to write the body to -o, the headers to -D, and print only the status
# code on stdout. The stub has to honour all three or the script reads a status of "000" forever.
cat > "$TMP/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=""; hdr=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -D) hdr="$2"; shift 2 ;;
    *) shift ;;
  esac
done
n_file="$FAKE_CURL_STATE"
n=0
[ ! -f "$n_file" ] || n="$(cat "$n_file")"
n=$((n + 1))
printf '%s\n' "$n" > "$n_file"

run() { # run <sha> <status> <conclusion-or-null> [path-suffix]
  printf '{"head_sha":"%s","path":"%s%s","status":"%s","conclusion":%s,"html_url":"https://x/%s"}' \
    "$1" "$WORKFLOW" "${4:-}" "$2" \
    "$([ "$3" = null ] && printf null || printf '"%s"' "$3")" "$2"
}
body() { printf '{"workflow_runs":[%s]}\n' "$1" > "$out"; }

: > "${hdr:-/dev/null}"
case "$FAKE_CURL_CASE:$n" in
  # A run for a different commit, then one still going, then the verdict.
  pass:1) body "$(run "$OTHER" completed success)" ;;
  pass:2) body "$(run "$SHA" in_progress null)" ;;
  pass:*) body "$(run "$SHA" completed success)" ;;
  # A cancelled sibling must not veto a run that actually passed, and the ref-qualified path a
  # branch dispatch produces must still match the workflow file.
  duplicate:*) body "$(run "$SHA" completed cancelled @refs/heads/topic),$(run "$SHA" completed success @refs/heads/topic)" ;;
  fail:*) body "$(run "$SHA" completed failure)" ;;
  cancelled:*) body "$(run "$SHA" completed cancelled)" ;;
  # A run whose every job was skipped proves nothing, so it must not stand in for a green one.
  skipped:*) body "$(run "$SHA" completed skipped)" ;;
  missing:*) body "" ;;
  # Another workflow was green on this very commit. It says nothing about this one.
  otherworkflow:*) printf '{"workflow_runs":[{"head_sha":"%s","path":".github/workflows/other.yml","status":"completed","conclusion":"success"}]}\n' "$SHA" > "$out" ;;
  ratelimited:1)
    printf 'x-ratelimit-reset: %s\r\n' "$(( $(date +%s) + 1 ))" > "${hdr:-/dev/null}"
    body ""
    printf '403\n'; exit 0 ;;
  ratelimited:*) body "$(run "$SHA" completed success)" ;;
  unauthorized:*) body ""; printf '401\n'; exit 0 ;;
  # curl's own failure, which the script must read as "no verdict", never as a pass.
  unreachable:*) exit 22 ;;
esac
printf '200\n'
SH
chmod +x "$TMP/curl"

run_case() { # run_case <case> <timeout>
  rm -f "$TMP/state"
  PATH="$TMP:$PATH" FAKE_CURL_STATE="$TMP/state" FAKE_CURL_CASE="$1" \
    MIRROR_REPO=example/repo MIRROR_CI_TIMEOUT="$2" MIRROR_CI_INTERVAL=1 \
    MIRROR_CI_TOKEN="${TOKEN_OVERRIDE-stub-read-token}" \
    bash "$ROOT/packaging/check-mirror-ci.sh" "$SHA" "$WORKFLOW"
}

# The token is mandatory: an unauthenticated poll gets 60 requests an hour per IP, shared by
# every runner, so the fallback answered 403 instead of answering the question.
if TOKEN_OVERRIDE="" run_case pass 5 >/dev/null 2>&1; then
  echo "check-mirror-ci polled GitHub with no MIRROR_CI_TOKEN" >&2
  exit 1
fi

refuses() { # refuses <case> <timeout> <description>
  if run_case "$1" "$2" >/dev/null 2>&1; then
    echo "check-mirror-ci accepted $3" >&2
    exit 1
  fi
}

run_case pass 30 >/dev/null
run_case duplicate 5 >/dev/null
refuses fail 5 "a failed run"
refuses cancelled 5 "a run that only ever cancelled"
refuses skipped 5 "a run that skipped every job"
refuses missing 2 "a commit the mirror never delivered"
refuses otherworkflow 2 "a different workflow's green run"
# A rate limit is not a verdict: every gate in flight would otherwise go red together whenever the
# shared IP's hourly quota runs out, each needing a hand to clear.
run_case ratelimited 30 >/dev/null
refuses unreachable 2 "an API that could not be reached"
# A dead credential must say so immediately rather than spend the timeout and then blame the run.
refuses unauthorized 60 "an expired token"

# The SHA is interpolated into a URL, so a malformed one is refused before it is ever sent.
#
# Bounded, and stubbed, like every case above: these assert that the script refuses ITS ARGUMENTS,
# and a regression that drops the check would otherwise fall through to the real poll loop on its
# 40-minute default and hang CI instead of failing it.
#
# Matched on the MESSAGE, not merely on a non-zero exit. Both of these would also "fail" by running
# the poll loop to its deadline against a stub that never matches — so an exit-status assertion
# passes just as happily with the validation deleted, which is no assertion at all.
bad_args() { # bad_args <description> <expected-message> <args...>
  local what="$1" want="$2"; shift 2
  local output
  output="$(PATH="$TMP:$PATH" FAKE_CURL_STATE="$TMP/state" FAKE_CURL_CASE=pass \
    MIRROR_REPO=example/repo MIRROR_CI_TIMEOUT=2 MIRROR_CI_INTERVAL=1 \
    MIRROR_CI_TOKEN=stub-read-token \
    bash "$ROOT/packaging/check-mirror-ci.sh" "$@" 2>&1)" && {
      echo "check-mirror-ci accepted $what" >&2
      exit 1
    }
  case "$output" in
    *"$want"*) ;;
    *) echo "check-mirror-ci rejected $what, but not for that reason: $output" >&2; exit 1 ;;
  esac
}
bad_args "a malformed SHA" "invalid commit SHA" not-a-sha "$WORKFLOW"
bad_args "no workflow argument" "usage: check-mirror-ci.sh" "$SHA"

echo "mirror CI gate: PASS"
