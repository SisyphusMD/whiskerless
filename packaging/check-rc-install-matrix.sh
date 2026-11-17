#!/usr/bin/env bash
# Refuse to cut a STABLE release when the candidate that was supposed to test it
# never passed its install matrix.
#   check-rc-install-matrix.sh <version>       e.g. 0.2.0
#
# Shared between both projects: they run the same install matrix, and a gate that exists in one
# and not the other is how a release ships untested in exactly the repo nobody was looking at. The
# per-project values come from packaging/project.env: the repo slug, and optionally
# INSTALL_MATRIX_WORKFLOWS, the Forgejo workflow files that together make up the matrix (default:
# install-matrix.yml). Every one of them must be green for the candidate.
#
# The install matrix runs AFTER a release — it installs published artifacts — so
# it can never gate the release it tests. What it can gate is the promotion: a
# candidate whose apt, dnf, Homebrew, .pkg, raw-binary or PyPI install is broken
# is not a thing to promote to stable, and noticing that should not depend on
# somebody remembering to open the right tab.
#
# Reads only and holds no write credential. FORGEJO_CI_TOKEN is optional: the projects are
# public and Forgejo serves their run status without one.
set -euo pipefail

VERSION="${1:?usage: $0 <version>}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
REPO="$PROJECT_REPO_SLUG"
FORGE="${FORGEJO_CI_SERVER:-https://forgejo.bryantserver.com}"
API="$FORGE/api/v1/repos/$REPO"
WORKFLOWS="${INSTALL_MATRIX_WORKFLOWS:-install-matrix.yml}"
# A list of nothing would check nothing and pass, so it is refused rather than read as empty.
[ -n "${WORKFLOWS//[[:space:]]/}" ] || {
  echo "::error::INSTALL_MATRIX_WORKFLOWS is blank — name at least one install-matrix workflow" >&2; exit 1; }

auth=()
[ -z "${FORGEJO_CI_TOKEN:-}" ] || auth=(-H "Authorization: token $FORGEJO_CI_TOKEN")

get() {  # get <url> — fails loudly rather than letting an error read as "no runs"
  curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 120 -sSf "${auth[@]}" "$1"
}

# The candidate this stable is promoting: the highest rc for THIS version, read
# from the LOCAL tags, then checked against the forge below.
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
# fetched since the newest candidate would quietly qualify an older, greener one.
# No `|| true`: a 5xx or malformed JSON would otherwise read as an empty result,
# which is the reading that lets a stale checkout through. A 404 is the one empty
# answer that is real: Forgejo answers it when no ref has that prefix.
code="$(curl --max-time 30 --retry 3 --retry-connrefused -sS -o /dev/null -w '%{http_code}' \
  "${auth[@]}" "$API/git/refs/tags/v${VERSION}-rc." || echo 000)"
case "$code" in
  200)
    remote_refs="$(get "$API/git/refs/tags/v${VERSION}-rc.")" || {
      echo "::error::could not ask Forgejo which candidates exist — refusing to promote on an unverified tag set" >&2; exit 1; }
    remote_rc="$(printf '%s' "$remote_refs" | jq -r '.[].ref' \
      | sed -n "s#^refs/tags/v${VERSION//./\\.}-rc\.\([0-9]\{1,\}\)\$#\1#p" \
      | sort -n | tail -n1)" || {
      echo "::error::Forgejo's tag list was unreadable — refusing to promote on an unverified tag set" >&2; exit 1; }
    ;;
  404) remote_rc="" ;;
  *)
    echo "::error::could not ask Forgejo which candidates exist (HTTP $code) — refusing to promote on an unverified tag set" >&2
    exit 1
    ;;
esac
if [ -n "$remote_rc" ] && [ "$remote_rc" -gt "$rc" ]; then
  echo "::error::Forgejo has v${VERSION}-rc.${remote_rc} but this checkout stops at rc.${rc} — fetch tags; qualifying a candidate that is not the newest is how a broken one gets promoted" >&2
  exit 1
fi

echo "the candidate being promoted is $TAG"

failures=""

# Forgejo's run objects carry neither head_branch nor a separate conclusion:
# `prettyref` is the ref, `status` is already the verdict. And it IGNORES
# `run-name`, so a run's title is the workflow name (dispatch) or the commit
# message (tag push) — neither says which tag was tested. A tag push is still
# recognisable by its ref; a re-dispatch runs from main (so a fix to these scripts
# is what re-runs, not the copies frozen at the tag) and is recognisable only by
# the JOB name, which Forgejo does evaluate and which carries the tag on purpose.
for workflow in $WORKFLOWS; do
  [[ "$workflow" =~ ^[A-Za-z0-9._-]+\.ya?ml$ ]] || {
    echo "::error::INSTALL_MATRIX_WORKFLOWS names '$workflow', which is not a workflow file name" >&2; exit 1; }
  # Scoped to this workflow server-side: the repo-wide listing is every run there
  # has ever been, and stops containing the one being asked about.
  runs="$(get "$API/actions/runs?workflow_id=$workflow&limit=50")" || {
    echo "::error::could not read the $workflow runs — refusing to guess" >&2; exit 1; }

  verdict="missing"
  # Newest first, so the most recent attempt for this tag is the one that counts.
  for run in $(printf '%s' "$runs" | jq -r '(.workflow_runs // []) | sort_by(.started // .created) | reverse | .[] | "\(.id):\(.prettyref):\(.status)"'); do
    run_id="${run%%:*}"; rest="${run#*:}"; ref="${rest%%:*}"; status="${rest#*:}"
    if [ "$ref" != "$TAG" ]; then
      # Not a push for this tag — the only other thing it can be is a dispatch that
      # named the tag in its job names.
      #
      # A failure to READ those names is not the same as "unrelated", and treating
      # it as such is a fail-open with teeth: this loop would walk past a newer
      # re-dispatch it could not classify and qualify the release on an OLDER green
      # tag-push run. So a run that cannot be classified stops the gate.
      jobs="$(get "$API/actions/runs/$run_id/jobs")" || {
        echo "::error::could not read the jobs of Forgejo run $run_id, so it cannot be told apart from a re-dispatch for $TAG — refusing to promote on an unclassified run" >&2
        exit 1; }
      printf '%s' "$jobs" | jq -e --arg t "$TAG" 'any(.[]?; .name | contains($t))' >/dev/null 2>&1 || continue
    fi
    verdict="$status"
    break
  done
  case "$verdict" in
    success) echo "  $workflow  $TAG passed" ;;
    *)       failures="$failures $workflow=$verdict" ;;
  esac
done

# --- verdict ------------------------------------------------------------------------
if [ -z "$failures" ]; then
  echo "$TAG passed its install matrix ($WORKFLOWS) — every channel installed and ran"
  exit 0
fi
case "$failures" in
  *missing*)
    echo "::error::$TAG has no install-matrix run for:$failures. Dispatch it against that tag and let it pass before promoting." >&2 ;;
  *running*|*waiting*|*blocked*)
    echo "::error::$TAG's install matrix is still going:$failures. Wait for it rather than promoting on an unknown." >&2 ;;
  *)
    echo "::error::$TAG's install matrix is not green:$failures. A candidate whose install channels are broken must not be promoted — fix it and re-dispatch the matrix against $TAG." >&2 ;;
esac
exit 1
