#!/usr/bin/env bash
# Create (or reuse) a GitHub release and upload assets, idempotently.
#   github-release.sh <token> <tag> <notes-file> [asset...]
#
# Mirror of forgejo-release.sh for the GitHub API. Both Forgejo (which adds the
# Linux binary, via GH_REPO_WRITE_PAT) and GitHub itself (which adds the .pkg, via
# the automatic GITHUB_TOKEN) call this with the SAME CHANGELOG notes, so whoever
# creates the release first sets identical notes and the other just appends.
set -euo pipefail
# Every curl is time-bounded: an unreachable host would otherwise hang here with
# no deadline at all, stranding the release targets sequenced after this one.
# Reads retry; creates and uploads do not, because a timed-out mutation may
# already have been applied and repeating it would duplicate rather than
# recover. The tag-wait loop is its own retry, so its request does not nest one.

token="$1"; tag="$2"; notes_file="$3"; shift 3
repo="SisyphusMD/whiskerless"
api="https://api.github.com/repos/$repo"
auth=(-H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json")

echo "waiting for tag $tag on GitHub…"
# 30 minutes, not 10: the push-mirror is asynchronous and a network blip on
# either side stretches it. rc.27 timed out at ten and cost that release its
# GitHub assets, on a tag that arrived shortly afterwards.
for _ in $(seq 1 180); do
  curl --max-time 20 -sf "${auth[@]}" "$api/git/refs/tags/$tag" >/dev/null && break
  sleep 10
done

id=$(curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 -sf "${auth[@]}" "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
if [ -z "$id" ]; then
  # Three workflows race to create this release (Forgejo publish.yml, and
  # GitHub's release-macos.yml + release-linux.yml). The read above is a
  # check-then-create, so two of them can both see nothing and both POST; the
  # loser gets 422 already_exists. Adopt the winner's release rather than
  # failing — every caller passes the same CHANGELOG section, so the notes it
  # already set are byte-identical to the ones being abandoned here.
  id=$(curl --max-time 300 -sS "${auth[@]}" -X POST "$api/releases" \
    -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" '{tag_name:$t,name:$t,body:$b,prerelease:($t|test("-rc\\."))}')" | jq -r '.id // empty')
  if [ -z "$id" ]; then
    id=$(curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 90 -sf "${auth[@]}" \
      "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
  fi
  [ -n "$id" ] || { echo "could not create or find the GitHub release for $tag" >&2; exit 1; }
fi
echo "GitHub release id: $id"

for f in "$@"; do
  name=$(basename "$f")
  # GitHub rewrites `~` to `.` in the STORED asset name, and enforces uniqueness
  # on that rewritten name. Looking up the local spelling therefore never matches
  # an asset already there, the delete is skipped, and the re-upload comes back
  # 422 already_exists — which under `set -e` aborts this script partway through
  # its asset list. That is the difference between "re-running a partial publish
  # completes it" (which this workflow is dispatchable in order to do) and a
  # re-run that replaces the raw binaries and then dies before SHA256SUMS,
  # leaving a checksum file that does not describe the binaries beside it.
  gh_name="${name//\~/.}"
  old=$(curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 -sf "${auth[@]}" "$api/releases/$id/assets" 2>/dev/null \
    | jq -r --arg n "$gh_name" '.[] | select(.name==$n) | .id' || true)
  [ -n "$old" ] && curl --max-time 300 -sf "${auth[@]}" -X DELETE "$api/releases/$id/assets/$old" >/dev/null || true
  curl --max-time 300 -sSf -H "Authorization: Bearer $token" -H "Content-Type: application/octet-stream" \
    --data-binary @"$f" "https://uploads.github.com/repos/$repo/releases/$id/assets?name=$gh_name" >/dev/null
  echo "  uploaded $gh_name → GitHub"
done
