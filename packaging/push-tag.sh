#!/usr/bin/env bash
# Push an annotated release tag atomically with its commit's branch, then best-effort nudge the
# push-mirrors to propagate it immediately.
#   push-tag.sh <tag> <token> <branch-ref>
#
# Used by release.yml's tag job only. prerelease.yml is dispatchable from any branch, so its own
# push step is kept inline rather than handing the repo-write PAT to a script whose content would
# come from whatever ref was dispatched; release.yml's tag job refuses non-main dispatches, so main
# is already the trust boundary the rest of the release pipeline relies on.
#
# An annotated tag object carries the release message and dates; a lightweight ref would let a
# later force-push retarget the version silently. Mirror-sync is warn-only: a scope refusal or
# hiccup there must never fail a release whose refs already fanned out via sync_on_commit.
set -euo pipefail
tag="${1:?usage: push-tag.sh <tag> <token> <branch-ref>}"
token="${2:?usage: push-tag.sh <tag> <token> <branch-ref>}"
branch_ref="${3:?usage: push-tag.sh <tag> <token> <branch-ref>}"

# Sourced for PROJECT_REPO_SLUG, which the mirror check below needs. Optional on purpose: this
# script's own job is pushing the tag, and a project without the file should still be able to
# do that — the check degrades to "unknown" rather than failing the push.
here="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$here/project.env" ]; then
  # shellcheck source=/dev/null
  . "$here/project.env"
fi

# Checked BEFORE the push, with the other preconditions. Asserting it after `git push`
# would publish the commit and tag and only then refuse, leaving the ref pushed and the job
# failed - the one outcome this script exists to avoid.
# Only when there is a mirror to check. Without project.env there is no slug, mirror_has_tag
# returns "unknown" without ever reaching GitHub, and demanding a token there would turn the
# documented degrade-to-unknown mode above into a refusal to push at all.
[ -z "${PROJECT_REPO_SLUG:-}" ] || \
  : "${GH_REPO_READ_PAT:?a read-only GitHub token is required: the mirror probe must not run unauthenticated, whose 60-requests-per-hour-per-IP ceiling every runner shares}"
[ "$(git cat-file -t "refs/tags/$tag")" = tag ]
[ "$(git rev-parse "$tag^{commit}")" = "$(git rev-parse HEAD)" ]
test -z "$(git status --porcelain)"

AUTH_B64=$(printf 'x-access-token:%s' "$token" | base64 | tr -d '\n')
git -c "http.extraheader=Authorization: Basic ${AUTH_B64}" push --atomic origin \
  "HEAD:${branch_ref}" "$tag"

# Fire the sync, then verify the OUTCOME on the mirror itself.
#
# Two things make the obvious version useless. `push_mirrors-sync` answers 403 to the
# repo-scoped token this script is given — that is why the call has always been best-effort —
# so a retry loop keyed on its result never runs. And Forgejo's own `last_error` is empty
# while a sync is still in flight, so an empty value proves nothing about an attempt just
# triggered. What is checkable without any extra scope is whether the tag actually arrived:
# a ref lookup on the mirror answers it directly, and a read-only token needs no scopes there.
#
# Warn-only by design. A release whose refs already fanned out must not be failed by a mirror,
# and reconcile heals a lagging one downstream. What this buys is that the tag is confirmed
# present — or its absence is named here, next to its cause, instead of surfacing 10 minutes
# later as an unexplained timeout in the job that waits for it.
#
# The read is authenticated. Unauthenticated github.com allows 60 requests an hour per IP and
# every runner shares one, so a bare probe answers 403 rather than answering, and a check that
# cannot decide is indistinguishable from one that was never run.
mirror_ref_json="${TMPDIR:-/tmp}/mirror-ref-$$.json"
want_obj=$(git rev-parse "refs/tags/${tag}")
mirror_has_tag() {
  [ -n "${PROJECT_REPO_SLUG:-}" ] || return 2   # nothing to check against
  code=$(curl -sS -o "$mirror_ref_json" -w '%{http_code}' --max-time 30 \
    -H "Authorization: Bearer ${GH_REPO_READ_PAT}" \
    "https://api.github.com/repos/${PROJECT_REPO_SLUG}/git/ref/tags/${tag}" 2>/dev/null) || return 2
  case "$code" in
    200) : ;;
    404) return 1 ;;   # definitively not there yet
    *)   return 2 ;;   # rate limited or unreachable: unknown, NOT success
  esac
  got=$(jq -r '.object.sha // empty' "$mirror_ref_json")
  [ -n "$got" ] || return 2
  # Existence is not propagation. A tag name can be reused after a partial prune, so a stale
  # same-named ref would answer 200 while still pointing at the previous object - and every job
  # that waits for this tag on the mirror would run against the wrong commit.
  [ "$got" = "$want_obj" ]
}

# One mutating request, then read-only polling. Repeating the POST would re-trigger a sync that
# may already be in flight, and a timed-out request can still have been applied; the retry that
# is safe to repeat is the GET.
curl -fsS --max-time 30 -X POST -H "Authorization: token ${token}" \
  "${GITHUB_SERVER_URL}/api/v1/repos/${GITHUB_REPOSITORY}/push_mirrors-sync" >/dev/null 2>&1 \
  || echo "::warning::push_mirrors-sync refused (PAT scope); relying on sync_on_commit"

for attempt in 1 2 3; do
  sleep $(( attempt * 20 ))
  # Captured before any other command runs: `$?` after an `if` is the status of the IF, not of
  # the probe, so reading it there always sees 0 and the unknown branch never fires.
  mirror_has_tag && status=0 || status=$?
  if [ "$status" = 0 ]; then
    echo "tag ${tag} confirmed on the mirror"
    break
  fi
  if [ "$status" = 2 ]; then
    echo "::warning::could not determine whether ${tag} reached the mirror (check unavailable)"
    break
  fi
  echo "::warning::${tag} not on the mirror yet (attempt ${attempt}/3)"
  [ "$attempt" = 3 ] && echo "::warning::${tag} never reached the mirror. The release continues, \
but any job waiting for this tag there will time out; re-run push_mirrors-sync with an \
admin-scoped token, or wait for the mirror interval"
done
