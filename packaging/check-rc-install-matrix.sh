#!/usr/bin/env bash
# Refuse to cut a STABLE release when the candidate that was supposed to test it
# never passed its install matrix.
#   check-rc-install-matrix.sh <version>       e.g. 0.2.0
#
# The install matrix runs AFTER a release — it installs published artifacts — so
# it can never gate the release it tests. What it can gate is the promotion: a
# candidate whose apt, dnf, Homebrew, .pkg, raw-binary or PyPI install is broken
# is not a thing to promote to stable, and noticing that should not depend on
# somebody remembering to open the right tab.
#
# Reads only, holds no write credential, and takes the same optional read token as
# check-mirror-ci.sh: unauthenticated GitHub allows 60 requests an hour per IP,
# shared with everything else leaving this network, and a rate-limited gate that
# cannot tell "red" from "could not ask" would block a good release.
set -euo pipefail

VERSION="${1:?usage: $0 <version>}"
REPO="SisyphusMD/whiskerless"
API="https://api.github.com/repos/$REPO"
WORKFLOW_FILE="install-matrix.yml"

auth=(-H "Accept: application/vnd.github+json")
[ -z "${GH_REPO_READ_PAT:-}" ] || auth+=(-H "Authorization: Bearer $GH_REPO_READ_PAT")

get() {  # get <url> — fails loudly rather than letting an error read as "no runs"
  curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 120 -sSf "${auth[@]}" "$1"
}

# The candidate this stable is promoting: the highest rc for THIS version, read
# from the LOCAL tags.
#
# Deliberately not from GitHub. This gate runs on Forgejo, which is where tags are
# made; the mirror is asynchronous, so a cut started while a fresh candidate is
# still in flight would ask GitHub, be told there are no candidates, and pass —
# fail-open at the one moment there is genuinely something to check. The checkout
# already holds every tag, so GitHub is asked only the question that is actually
# its own: what happened to that tag's workflow run.
git rev-parse --git-dir >/dev/null 2>&1 || {
  echo "::error::not a git checkout — the candidate is derived from the local tags" >&2; exit 1; }
git tag -l 'v*.*.*' | grep -q . || {
  echo "::error::this checkout has no release tags (a shallow clone?) — refusing to conclude there is no candidate" >&2; exit 1; }
rc="$(git tag -l "v${VERSION}-rc.*" \
  | sed -n "s#^v${VERSION//./\\.}-rc\.\([0-9]\{1,\}\)\$#\1#p" \
  | sort -n | tail -n1 || true)"

if [ -z "$rc" ]; then
  # Not every version has to go through a candidate; say so rather than inventing
  # a blocker for a flow that may be deliberate.
  echo "no v${VERSION}-rc.* candidate exists — nothing for this gate to check"
  exit 0
fi
TAG="v${VERSION}-rc.${rc}"

# Local tags are authoritative only if they are CURRENT. A checkout that has not
# fetched since the newest candidate would quietly qualify an older, greener one —
# the same fail-open as asking the lagging mirror, just from the other side. The
# mirror can legitimately be behind (it is asynchronous), so being behind is fine;
# being AHEAD means this checkout is the stale one.
# No `|| true`: a rate limit, a 5xx or malformed JSON would otherwise read as an
# empty result, which is indistinguishable from "the mirror is behind" — and that
# is the reading that lets a stale checkout through. Only a SUCCESSFUL empty
# answer means behind.
remote_refs="$(get "$API/git/matching-refs/tags/v${VERSION}-rc.")" || {
  echo "::error::could not ask the mirror which candidates exist — refusing to promote on an unverified tag set" >&2; exit 1; }
remote_rc="$(printf '%s' "$remote_refs" | jq -r '.[].ref' \
  | sed -n "s#^refs/tags/v${VERSION//./\\.}-rc\.\([0-9]\{1,\}\)\$#\1#p" \
  | sort -n | tail -n1)"
if [ -n "$remote_rc" ] && [ "$remote_rc" -gt "$rc" ]; then
  echo "::error::the mirror knows v${VERSION}-rc.${remote_rc} but this checkout stops at rc.${rc} — fetch tags; qualifying a candidate that is not the newest is how a broken one gets promoted" >&2
  exit 1
fi

echo "the candidate being promoted is $TAG"

# Scoped to this workflow, not the last hundred runs of all of them: a tag fires
# ci, publish, bottles, the pkg build and hassfest as well, so a repo-wide page
# stops containing the run being asked about after very little activity.
runs="$(get "$API/actions/workflows/$WORKFLOW_FILE/runs?per_page=100")" || {
  echo "::error::could not read install-matrix runs — refusing to guess" >&2; exit 1; }

# Two ways a run can belong to this tag, and both have to count. A tag PUSH
# carries head_branch = the tag. A re-dispatch cannot: it is dispatched from main
# on purpose, so that a fix to these scripts is what re-runs rather than the
# copies frozen at the tag — and it names its subject only in the run-name. Match
# only head_branch and the gate would go on failing a candidate that has since
# been re-dispatched green, which is precisely what its own error message tells
# you to do.
verdict="$(printf '%s' "$runs" | jq -r --arg t "$TAG" --arg rn "Install matrix $TAG" '
  [.workflow_runs[] | select(.head_branch == $t or .display_title == $rn)]
  | sort_by(.run_started_at) | last
  | if . == null then "missing" else "\(.status)/\(.conclusion // "-")" end')"

case "$verdict" in
  "completed/success")
    echo "$TAG passed its install matrix — every channel installed and ran"
    ;;
  missing)
    echo "::error::$TAG has no install-matrix run at all. Dispatch it against that tag and let it pass before promoting." >&2
    exit 1
    ;;
  completed/*)
    echo "::error::$TAG's install matrix is $verdict. A candidate whose install channels are broken must not be promoted — fix it and re-dispatch the matrix against $TAG." >&2
    exit 1
    ;;
  *)
    echo "::error::$TAG's install matrix is still $verdict. Wait for it rather than promoting on an unknown." >&2
    exit 1
    ;;
esac
