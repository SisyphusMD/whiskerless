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
FORGE="https://forgejo.bryantserver.com"

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

# The matrix has TWO halves on two forges — Linux on ours, macOS on GitHub,
# because Forgejo has no macOS runner (docs/design/ci-split.md). Requiring only
# one would qualify a candidate on half a matrix, which is the same fail-open as
# not checking at all, just harder to notice.
failures=""

# --- the macOS half, on GitHub ------------------------------------------------------
# Scoped to this workflow, not the last hundred runs of all of them: a tag fires
# ci, publish, bottles, the pkg build and hassfest as well, so a repo-wide page
# stops containing the run being asked about after very little activity.
#
# Two ways a run can belong to this tag, and both have to count. A tag PUSH
# carries head_branch = the tag. A re-dispatch cannot: it is dispatched from main
# on purpose, so that a fix to these scripts is what re-runs rather than the
# copies frozen at the tag — and it names its subject only in the run-name.
gh_runs="$(get "$API/actions/workflows/install-matrix.yml/runs?per_page=100")" || {
  echo "::error::could not read the macOS install-matrix runs — refusing to guess" >&2; exit 1; }
macos="$(printf '%s' "$gh_runs" | jq -r --arg t "$TAG" --arg rn "Install matrix (macOS) $TAG" '
  [.workflow_runs[] | select(.head_branch == $t or .display_title == $rn)]
  | sort_by(.run_started_at) | last
  | if . == null then "missing" else "\(.status)/\(.conclusion // "-")" end')"
case "$macos" in
  "completed/success") echo "  macOS  $TAG passed" ;;
  *)                   failures="$failures macOS=$macos" ;;
esac

# --- the Linux half, on Forgejo -----------------------------------------------------
# Read unauthenticated: this instance serves run status publicly, so the gate
# keeps holding no credential. Forgejo's run objects carry neither head_branch nor
# a separate conclusion — `prettyref` is the ref, `status` is already the verdict,
# and `title` is the run-name, which is the only thing a dispatch from main
# records about which tag it tested.
# Scoped to this workflow server-side. The repo-wide listing is every run there
# has ever been, and Forgejo ignores `limit` today — which is exactly the kind of
# undocumented generosity a promotion gate should not depend on. `workflow_id`
# bounds it to install-matrix runs, of which there is about one per tag.
#
# Not also filtered by `ref`: that wants the full `refs/tags/...` form and would
# drop a re-dispatch, which runs from main and names its tag only in the run-name.
fj_runs="$(curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 120 -sSf \
  "$FORGE/api/v1/repos/$REPO/actions/runs?workflow_id=install-matrix.yml")" || {
  echo "::error::could not read the Linux install-matrix runs — refusing to guess" >&2; exit 1; }
# The `(macOS)` exclusion is belt and braces. `workflow_id` is the BARE filename,
# and both halves are called install-matrix.yml — so if this instance ever served
# runs for .github/workflows too (it serves none today, across every run in the
# repo's history), the twin would match this tag as well and `last` could answer
# with a run whose jobs were all skipped. The run-names are what tell them apart.
linux="$(printf '%s' "$fj_runs" | jq -r --arg t "$TAG" --arg rn "Install matrix (Linux) $TAG" '
  [.workflow_runs[]
   | select(.workflow_id == "install-matrix.yml")
   | select(.title | contains("(macOS)") | not)
   | select(.prettyref == $t or .title == $rn)]
  | sort_by(.started // .created) | last
  | if . == null then "missing" else .status end')"
case "$linux" in
  success) echo "  Linux  $TAG passed" ;;
  *)       failures="$failures Linux=$linux" ;;
esac

# --- verdict ------------------------------------------------------------------------
if [ -z "$failures" ]; then
  echo "$TAG passed its install matrix on both forges — every channel installed and ran"
  exit 0
fi
case "$failures" in
  *missing*)
    echo "::error::$TAG has no install-matrix run for:$failures. Dispatch it against that tag and let it pass before promoting." >&2 ;;
  *running*|*waiting*)
    echo "::error::$TAG's install matrix is still going:$failures. Wait for it rather than promoting on an unknown." >&2 ;;
  *)
    echo "::error::$TAG's install matrix is not green:$failures. A candidate whose install channels are broken must not be promoted — fix it and re-dispatch the matrix against $TAG." >&2 ;;
esac
exit 1
