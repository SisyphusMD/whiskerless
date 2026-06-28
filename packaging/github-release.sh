#!/usr/bin/env bash
# Create (or reuse) a GitHub release and upload assets, idempotently.
#   github-release.sh <token> <tag> <notes-file> [asset...]
#
# Mirror of forgejo-release.sh for the GitHub API. Both Forgejo (which adds the
# Linux binary, via GH_REPO_WRITE_PAT) and GitHub itself (which adds the .pkg, via
# the automatic GITHUB_TOKEN) call this with the SAME CHANGELOG notes, so whoever
# creates the release first sets identical notes and the other just appends.
set -euo pipefail

token="$1"; tag="$2"; notes_file="$3"; shift 3
repo="SisyphusMD/whiskerless"
api="https://api.github.com/repos/$repo"
auth=(-H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json")

echo "waiting for tag $tag on GitHub…"
for _ in $(seq 1 60); do
  curl -sf "${auth[@]}" "$api/git/refs/tags/$tag" >/dev/null && break
  sleep 10
done

id=$(curl -sf "${auth[@]}" "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
if [ -z "$id" ]; then
  id=$(curl -sSf "${auth[@]}" -X POST "$api/releases" \
    -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" '{tag_name:$t,name:$t,body:$b}')" | jq -r .id)
fi
echo "GitHub release id: $id"

for f in "$@"; do
  name=$(basename "$f")
  old=$(curl -sf "${auth[@]}" "$api/releases/$id/assets" 2>/dev/null \
    | jq -r ".[] | select(.name==\"$name\") | .id" || true)
  [ -n "$old" ] && curl -sf "${auth[@]}" -X DELETE "$api/releases/$id/assets/$old" >/dev/null || true
  curl -sSf -H "Authorization: Bearer $token" -H "Content-Type: application/octet-stream" \
    --data-binary @"$f" "https://uploads.github.com/repos/$repo/releases/$id/assets?name=$name" >/dev/null
  echo "  uploaded $name → GitHub"
done
