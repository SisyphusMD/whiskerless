#!/usr/bin/env bash
# packaging/check-forgejo-ci.sh against a stubbed Forgejo, with no network.
#
# This gate decides whether a release may be cut, and most of its interesting paths are responses
# nobody can reproduce on demand: a run not created yet, one still going, a cancelled run beside a
# successful one, a refused credential. Stubbing curl is the only way to reach them before they
# happen during a release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SHA=0123456789abcdef0123456789abcdef01234567
OTHER=89abcdef0123456789abcdef0123456789abcdef
WORKFLOW=macos.yml
export SHA OTHER WORKFLOW

# The real script asks curl to write the body to -o and print only the status code on stdout. The
# stub honours both, and records whether it was sent a credential.
cat > "$TMP/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=""; url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) shift 2 ;;
    -H) case "$2" in Authorization:*) echo auth > "$FAKE_CURL_STATE.auth" ;; esac; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done

# The jobs of a run that concluded "success". Answered apart from the run list, so the run-list
# sequences below keep their numbering.
case "$url" in
  */jobs)
    job() { printf '{"name":"%s","status":"%s"}' "$1" "$2"; }
    case "$FAKE_CURL_CASE" in
      # macos-scope.sh scoped a Renovate push out: the run is "success", the Macs never ran.
      scopedout) printf '[%s,%s,%s]\n' "$(job scope success)" "$(job floor skipped)" "$(job current skipped)" > "$out" ;;
      # One scoped-out run beside one that really ran: the real one decides.
      scopedandreal) case "$url" in
          */runs/1/jobs) printf '[%s,%s]\n' "$(job scope success)" "$(job floor skipped)" > "$out" ;;
          *) printf '[%s,%s]\n' "$(job scope success)" "$(job floor success)" > "$out" ;;
        esac ;;
      jobserror) printf '502\n'; exit 0 ;;
      emptyjobs) printf '[]\n' > "$out" ;;
      *) printf '[%s,%s]\n' "$(job scope success)" "$(job floor success)" > "$out" ;;
    esac
    printf '200\n'; exit 0 ;;
esac
n_file="$FAKE_CURL_STATE"
n=0
[ ! -f "$n_file" ] || n="$(cat "$n_file")"
n=$((n + 1))
printf '%s\n' "$n" > "$n_file"

run() { # run <sha> <status> [workflow] [id]
  printf '{"id":%s,"commit_sha":"%s","workflow_id":"%s","status":"%s","html_url":"https://x/%s"}' \
    "${4:-7}" "$1" "${3:-$WORKFLOW}" "$2" "$2"
}
body() { printf '{"workflow_runs":[%s],"total_count":1}\n' "$1" > "$out"; }

case "$FAKE_CURL_CASE:$n" in
  # A run for a different commit (the server filter is not trusted), one still going, the verdict.
  pass:1) body "$(run "$OTHER" success)" ;;
  pass:2) body "$(run "$SHA" running)" ;;
  pass:3) body "$(run "$SHA" waiting)" ;;
  pass:*) body "$(run "$SHA" success)" ;;
  # A cancelled sibling must not veto a run that actually passed.
  duplicate:*) body "$(run "$SHA" cancelled),$(run "$SHA" success)" ;;
  fail:*) body "$(run "$SHA" failure)" ;;
  cancelled:*) body "$(run "$SHA" cancelled)" ;;
  # A run whose every job was skipped proves nothing, so it must not stand in for a green one.
  skipped:*) body "$(run "$SHA" skipped)" ;;
  # A failure beside a run still going is not a verdict yet; the rerun may still pass.
  rerunning:1) body "$(run "$SHA" failure),$(run "$SHA" running)" ;;
  rerunning:*) body "$(run "$SHA" failure),$(run "$SHA" success)" ;;
  missing:*) body "" ;;
  nullruns:*) printf '{"workflow_runs":null,"total_count":0}\n' > "$out" ;;
  # Another workflow was green on this very commit. It says nothing about this one.
  otherworkflow:*) body "$(run "$SHA" success ci.yml)" ;;
  # A server error is retried, never read as a verdict.
  flaky:1) body ""; printf '502\n'; exit 0 ;;
  flaky:*) body "$(run "$SHA" success)" ;;
  unauthorized:*) body ""; printf '401\n'; exit 0 ;;
  forbidden:*) body ""; printf '403\n'; exit 0 ;;
  # curl's own failure, which the script must read as "no verdict", never as a pass.
  unreachable:*) exit 7 ;;
  scopedout:*|jobserror:*|emptyjobs:*) body "$(run "$SHA" success)" ;;
  scopedandreal:*) body "$(run "$SHA" success "" 1),$(run "$SHA" success "" 2)" ;;
esac
printf '200\n'
SH
chmod +x "$TMP/curl"

run_case() { # run_case <case> <timeout>
  rm -f "$TMP/state" "$TMP/state.auth"
  PATH="$TMP:$PATH" FAKE_CURL_STATE="$TMP/state" FAKE_CURL_CASE="$1" \
    FORGEJO_CI_REPO=example/repo FORGEJO_CI_TIMEOUT="$2" FORGEJO_CI_INTERVAL=0 \
    FORGEJO_CI_TOKEN="${TOKEN_OVERRIDE-stub-read-token}" \
    bash "$ROOT/packaging/check-forgejo-ci.sh" "$SHA" "$WORKFLOW"
}

refuses() { # refuses <case> <timeout> <description>
  if run_case "$1" "$2" >/dev/null 2>&1; then
    echo "check-forgejo-ci accepted $3" >&2
    exit 1
  fi
}

run_case pass 30 >/dev/null
[ -f "$TMP/state.auth" ] || { echo "check-forgejo-ci dropped FORGEJO_CI_TOKEN" >&2; exit 1; }
# Public repositories read without a token, and none must be invented.
TOKEN_OVERRIDE="" run_case pass 30 >/dev/null
[ ! -f "$TMP/state.auth" ] || { echo "check-forgejo-ci sent a credential it was not given" >&2; exit 1; }
run_case duplicate 5 >/dev/null
run_case rerunning 30 >/dev/null
run_case flaky 30 >/dev/null
refuses fail 5 "a failed run"
refuses cancelled 5 "a run that only ever cancelled"
refuses skipped 5 "a run that skipped every job"
refuses missing 1 "a commit with no run"
refuses nullruns 1 "an empty run list"
refuses otherworkflow 1 "a different workflow's green run"
refuses unreachable 1 "an API that could not be reached"
# A "success" run is not a pass by itself: every job in it has to have run and passed.
refuses scopedout 1 "a run whose macOS jobs were all skipped"
refuses jobserror 1 "a run whose jobs could not be read"
refuses emptyjobs 1 "a run with no jobs listed"
run_case scopedandreal 5 >/dev/null

# A refused credential must say so at once rather than spend the timeout and then blame the run.
fast_refusal() { # fast_refusal <case>
  local start out
  start="$(date +%s)"
  if out="$(run_case "$1" 60 2>&1)"; then
    echo "check-forgejo-ci accepted a $1 answer" >&2; exit 1
  fi
  [ $(( $(date +%s) - start )) -lt 30 ] || { echo "check-forgejo-ci waited out a $1 answer" >&2; exit 1; }
  case "$out" in *"refused the read"*) ;; *) echo "check-forgejo-ci: unexpected $1 output: $out" >&2; exit 1 ;; esac
}
fast_refusal unauthorized
fast_refusal forbidden

# Matched on the MESSAGE, not merely on a non-zero exit: with the validation deleted, these would
# also fail, by polling the stub to the deadline, so an exit-status check would prove nothing.
bad_args() { # bad_args <description> <expected-message> <args...>
  local what="$1" want="$2"; shift 2
  local output
  output="$(PATH="$TMP:$PATH" FAKE_CURL_STATE="$TMP/state" FAKE_CURL_CASE=pass \
    FORGEJO_CI_REPO=example/repo FORGEJO_CI_TIMEOUT=1 FORGEJO_CI_INTERVAL=0 \
    bash "$ROOT/packaging/check-forgejo-ci.sh" "$@" 2>&1)" && {
      echo "check-forgejo-ci accepted $what" >&2
      exit 1
    }
  case "$output" in
    *"$want"*) ;;
    *) echo "check-forgejo-ci rejected $what, but not for that reason: $output" >&2; exit 1 ;;
  esac
}
bad_args "a malformed SHA" "invalid commit SHA" not-a-sha "$WORKFLOW"
bad_args "a workflow path instead of a file name" "invalid workflow file" "$SHA" ".forgejo/workflows/macos.yml"
bad_args "a workflow name carrying URL syntax" "invalid workflow file" "$SHA" "macos.yml&head_sha=x"
bad_args "no workflow argument" "usage: check-forgejo-ci.sh" "$SHA"

echo "Forgejo CI gate: PASS"
