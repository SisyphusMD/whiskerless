#!/usr/bin/env bash
# Refuse to cut a STABLE release when the candidate that was supposed to test it
# never passed its install matrix.
#   check-rc-install-matrix.sh <version>       e.g. 0.2.0
#
# Shared between both projects: they run the same two-forge install matrix, under the same two
# workflow names, and a gate that exists in one and not the other is how a release ships untested
# in exactly the repo nobody was looking at. The only per-project value is the repo slug, which
# comes from packaging/project.env.
#
# The install matrix runs AFTER a release — it installs published artifacts — so
# it can never gate the release it tests. What it can gate is the promotion: a
# candidate whose apt, dnf, Homebrew, .pkg, raw-binary or PyPI install is broken
# is not a thing to promote to stable, and noticing that should not depend on
# somebody remembering to open the right tab.
#
# Reads only and holds no write credential, but GH_REPO_READ_PAT is required, as it is for
# check-mirror-ci.sh. Unauthenticated GitHub allows 60 requests an hour per IP, shared with
# everything else leaving this network, and a gate that cannot tell "red" from "could not ask"
# is worse than no gate. A read-only token needs no scopes for a public repository, so requiring
# it costs nothing this job was protecting.
set -euo pipefail

VERSION="${1:?usage: $0 <version>}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
REPO="$PROJECT_REPO_SLUG"
API="https://api.github.com/repos/$REPO"
FORGE="https://forgejo.bryantserver.com"

auth=(-H "Accept: application/vnd.github+json")
# Required, never optional. Falling back to an unauthenticated call buys a 60/hour ceiling
# shared by every runner, so the probe starts answering 403 instead of answering.
: "${GH_REPO_READ_PAT:?a read-only GitHub token is required}"
auth+=(-H "Authorization: Bearer $GH_REPO_READ_PAT")

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

# The matrix has TWO halves on two forges, split by what the hardware can do:
# Linux amd64 on ours, macOS and Linux arm64 on GitHub's native runners
# (docs/design/ci-split.md). Requiring only one would qualify a candidate on half a
# matrix, which is the same fail-open as not checking at all, just harder to notice.
failures=""

# --- the macOS + Linux arm64 half, on GitHub ----------------------------------------
# Scoped to this workflow, not the last hundred runs of all of them: a tag fires
# ci, publish, bottles, the pkg build and hassfest as well, so a repo-wide page
# stops containing the run being asked about after very little activity.
#
# Two ways a run can belong to this tag, and both have to count. A tag PUSH
# carries head_branch = the tag. A re-dispatch cannot: it is dispatched from main
# on purpose, so that a fix to these scripts is what re-runs rather than the
# copies frozen at the tag — and it names its subject only in the run-name.
gh_runs="$(get "$API/actions/workflows/install-matrix.yml/runs?per_page=100")" || {
  echo "::error::could not read the GitHub install-matrix runs — refusing to guess" >&2; exit 1; }
github="$(printf '%s' "$gh_runs" | jq -r --arg t "$TAG" --arg rn "Install matrix (macOS + Linux arm64) $TAG" '
  [.workflow_runs[] | select(.head_branch == $t or .display_title == $rn)]
  | sort_by(.run_started_at) | last
  | if . == null then "missing" else "\(.status)/\(.conclusion // "-")" end')"
case "$github" in
  "completed/success") echo "  macOS + Linux arm64  $TAG passed" ;;
  *)                   failures="$failures macOS+arm64=$github" ;;
esac

# --- the Linux amd64 half, on Forgejo -----------------------------------------------
# Read unauthenticated: this instance serves run status publicly, so the gate keeps
# holding no credential. Scoped to this workflow server-side — the repo-wide listing
# is every run there has ever been, and Forgejo ignores `limit` today, which is the
# kind of undocumented generosity a promotion gate should not depend on.
#
# Forgejo's run objects carry neither head_branch nor a separate conclusion:
# `prettyref` is the ref, `status` is already the verdict. And it IGNORES
# `run-name`, so a run's title is the workflow name (dispatch) or the commit
# message (tag push) — neither says which tag was tested. A tag push is still
# recognisable by its ref; a re-dispatch runs from main and is recognisable only by
# the JOB name, which Forgejo does evaluate and which carries the tag on purpose.
fj_url="$FORGE/api/v1/repos/$REPO/actions/runs?workflow_id=install-matrix.yml"
fj_runs="$(curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 120 -sSf "$fj_url")" || {
  echo "::error::could not read the Linux install-matrix runs — refusing to guess" >&2; exit 1; }

linux="missing"
# Newest first, so the most recent attempt for this tag is the one that counts.
for run in $(printf '%s' "$fj_runs" | jq -r '.workflow_runs | sort_by(.started // .created) | reverse | .[] | "\(.id):\(.prettyref):\(.status)"'); do
  run_id="${run%%:*}"; rest="${run#*:}"; ref="${rest%%:*}"; status="${rest#*:}"
  if [ "$ref" != "$TAG" ]; then
    # Not a push for this tag — the only other thing it can be is a dispatch that
    # named the tag in its job names.
    #
    # A failure to READ those names is not the same as "unrelated", and treating
    # it as such is a fail-open with teeth: this loop would walk past a newer
    # re-dispatch it could not classify and qualify the release on an OLDER green
    # tag-push run. So a run that cannot be classified stops the gate.
    jobs="$(curl --max-time 30 --retry 3 --retry-connrefused -sSf \
      "$FORGE/api/v1/repos/$REPO/actions/runs/$run_id/jobs")" || {
      echo "::error::could not read the jobs of Forgejo run $run_id, so it cannot be told apart from a re-dispatch for $TAG — refusing to promote on an unclassified run" >&2
      exit 1; }
    printf '%s' "$jobs" | jq -e --arg t "$TAG" 'any(.[]?; .name | contains($t))' >/dev/null 2>&1 || continue
  fi
  linux="$status"
  break
done
case "$linux" in
  success) echo "  Linux amd64          $TAG passed" ;;
  *)       failures="$failures Linux-amd64=$linux" ;;
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
