#!/usr/bin/env bash
# packaging/check-rc-install-matrix.sh against a stubbed Forgejo and throwaway tags, with no network.
#
# The gate guards the stable cut, and every way it can be wrong is quiet: a stale checkout that
# qualifies an older candidate, a re-dispatch it cannot recognise, a run it cannot classify, a
# matrix workflow it never asked about. Each of those is staged here before a release can find it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A consumer-shaped checkout: the gate sources project.env next to itself and reads local tags.
mkdir -p "$TMP/repo/packaging" "$TMP/bin"
cp "$ROOT/packaging/check-rc-install-matrix.sh" "$TMP/repo/packaging/"
echo 'PROJECT_REPO_SLUG="example/repo"' > "$TMP/repo/packaging/project.env"
git -C "$TMP/repo" init -q -b main
git -C "$TMP/repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m base
for t in v0.9.0 v1.0.0-rc.1 v1.0.0-rc.2; do git -C "$TMP/repo" tag "$t"; done

# Serves the case's answer per URL. Honours -o (body file), -w (status code on stdout) and -f
# (non-2xx is an error), which is everything the gate asks of curl.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=""; fmt=""; fail=false; url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -H|--max-time|--retry|--retry-max-time) shift 2 ;;
    -sSf|-f) fail=true; shift ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
code=200; body=""
run() { printf '{"id":%s,"prettyref":"%s","status":"%s","started":"%s"}' "$1" "$2" "$3" "$4"; }
case "$FAKE_CASE:$url" in
  *"/git/refs/tags/v1.0.0-rc.")
    case "$FAKE_CASE" in
      ahead) body='[{"ref":"refs/tags/v1.0.0-rc.2"},{"ref":"refs/tags/v1.0.0-rc.3"}]' ;;
      notags) code=404; body='{"message":"not found"}' ;;
      tagerror) code=500; body='oops' ;;
      *) body='[{"ref":"refs/tags/v1.0.0-rc.1"},{"ref":"refs/tags/v1.0.0-rc.2"}]' ;;
    esac ;;
  *"workflow_id=install-matrix.yml&"*)
    case "$FAKE_CASE" in
      pass|ahead|notags|tagerror|twowf|twowfmissing) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.2 success 2026-01-02)]}" ;;
      # A newer re-dispatch from main, recognisable only by its job names, beats an older red push.
      redispatch) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.2 failure 2026-01-01),$(run 11 main success 2026-01-02)]}" ;;
      # The newest attempt for the tag counts, even when an older one was green.
      newestred) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.2 success 2026-01-01),$(run 11 main failure 2026-01-02)]}" ;;
      unclassified) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.2 success 2026-01-01),$(run 12 main success 2026-01-02)]}" ;;
      older) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.1 success 2026-01-02)]}" ;;
      running) body="{\"workflow_runs\":[$(run 10 v1.0.0-rc.2 running 2026-01-02)]}" ;;
      nullruns) body='{"workflow_runs":null}' ;;
      runserror) code=502 ;;
    esac ;;
  *"workflow_id=install-matrix-arm64.yml&"*)
    case "$FAKE_CASE" in
      twowf) body="{\"workflow_runs\":[$(run 20 v1.0.0-rc.2 success 2026-01-02)]}" ;;
      twowfmissing) body='{"workflow_runs":[]}' ;;
    esac ;;
  *"/actions/runs/11/jobs") body='[{"name":"Wait for v1.0.0-rc.2 assets"}]' ;;
  *"/actions/runs/12/jobs") code=500 ;;
  *"/jobs") body='[{"name":"something else"}]' ;;
  *) code=404 ;;
esac
if [ -n "$out" ]; then printf '%s' "$body" > "$out"; else printf '%s' "$body"; fi
[ -z "$fmt" ] || printf '%s' "$code"
if [ "$fail" = true ] && [ "$code" -ge 400 ]; then exit 22; fi
exit 0
SH
chmod +x "$TMP/bin/curl"

gate() { # gate <case> <version> [workflows]
  (cd "$TMP/repo" && PATH="$TMP/bin:$PATH" FAKE_CASE="$1" INSTALL_MATRIX_WORKFLOWS="${3-install-matrix.yml}" \
    bash packaging/check-rc-install-matrix.sh "$2" 2>&1)
}
passes() { # passes <case> <description> [workflows]
  gate "$1" 1.0.0 ${3:+"$3"} >/dev/null || { echo "FAIL: refused $2"; gate "$1" 1.0.0 ${3:+"$3"} || true; exit 1; }
  echo "ok   passes $2"
}
refuses() { # refuses <case> <description> <expected-message> [workflows]
  local out
  if out="$(gate "$1" 1.0.0 ${4+"$4"})"; then echo "FAIL: accepted $2"; exit 1; fi
  case "$out" in *"$3"*) echo "ok   refuses $2" ;; *) echo "FAIL: refused $2 for another reason: $out"; exit 1 ;; esac
}

passes pass "a green tag-push run for the newest candidate"
passes notags "a forge that has no candidate refs yet (404 is a real empty answer)"
passes redispatch "a newer green re-dispatch named in its job names"
passes twowf "every listed matrix workflow green" "install-matrix.yml install-matrix-arm64.yml"
refuses ahead "a checkout behind the forge's newest candidate" "fetch tags"
refuses tagerror "a forge that could not list candidates" "unverified tag set"
refuses newestred "an older green run when the newest attempt is red" "not green"
refuses unclassified "a newer run whose jobs could not be read" "unclassified run"
refuses older "a green run for an older candidate only" "no install-matrix run"
refuses running "a matrix still running" "still going"
refuses nullruns "an empty run list" "no install-matrix run"
refuses runserror "a run list that could not be read" "refusing to guess"
refuses twowfmissing "a listed matrix workflow with no run" "install-matrix-arm64.yml=missing" "install-matrix.yml install-matrix-arm64.yml"
refuses pass "a workflow list carrying URL syntax" "not a workflow file name" "install-matrix.yml&x=1"
refuses pass "a blank workflow list" "is blank" "   "

# A version with no candidate at all is not something to block.
out="$(gate pass 2.0.0)" || { echo "FAIL: blocked a version with no candidate: $out"; exit 1; }
case "$out" in *"no v2.0.0-rc.* candidate"*) echo "ok   passes a version with no candidate" ;; *) echo "FAIL: $out"; exit 1 ;; esac

# A tagless (shallow) checkout must not conclude there is no candidate.
git -C "$TMP/repo" tag -l | xargs git -C "$TMP/repo" tag -d >/dev/null
if out="$(gate pass 1.0.0)"; then echo "FAIL: passed on a tagless checkout"; exit 1; fi
case "$out" in *"no release tags"*) echo "ok   refuses a tagless checkout" ;; *) echo "FAIL: $out"; exit 1 ;; esac

echo "rc install-matrix gate: PASS"
