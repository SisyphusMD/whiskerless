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

[ "$(git cat-file -t "refs/tags/$tag")" = tag ]
[ "$(git rev-parse "$tag^{commit}")" = "$(git rev-parse HEAD)" ]
test -z "$(git status --porcelain)"

AUTH_B64=$(printf 'x-access-token:%s' "$token" | base64 | tr -d '\n')
git -c "http.extraheader=Authorization: Basic ${AUTH_B64}" push --atomic origin \
  "HEAD:${branch_ref}" "$tag"

curl -fsS -X POST -H "Authorization: token ${token}" \
  "${GITHUB_SERVER_URL}/api/v1/repos/${GITHUB_REPOSITORY}/push_mirrors-sync" \
  || echo "::warning::push_mirrors-sync refused (PAT scope); relying on sync_on_commit"
