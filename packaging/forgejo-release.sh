#!/usr/bin/env bash
# Create (or reuse) a Forgejo/Gitea release and upload assets, idempotently.
#   forgejo-release.sh <host> <token> <tag> <notes-file> [asset...]
#
# Waits for the tag to exist first (push-mirrors can lag), so a release is never
# created against a missing tag. Re-running replaces same-named assets, so the
# Forgejo (binary) and GitHub (.pkg) publishers can target the same release in
# any order.
set -euo pipefail
# Every curl is time-bounded: an unreachable host would otherwise hang here with
# no deadline at all, stranding the release targets sequenced after this one.
# Reads retry; creates and uploads do not, because a timed-out mutation may
# already have been applied and repeating it would duplicate rather than
# recover. The tag-wait loop is its own retry, so its request does not nest one.

host="$1"; token="$2"; tag="$3"; notes_file="$4"; shift 4
api="https://$host/api/v1/repos/SisyphusMD/whiskerless"
auth=(-H "Authorization: token $token")

echo "waiting for tag $tag on $host…"
for _ in $(seq 1 60); do
  curl --max-time 20 -skf "${auth[@]}" "$api/tags/$tag" >/dev/null && break
  sleep 10
done

id=$(curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 -skf "${auth[@]}" "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
if [ -z "$id" ]; then
  # Check-then-create, with up to three workflows racing (see github-release.sh).
  # A loser gets a duplicate-tag error and no id; re-read and adopt the winner's
  # release, whose notes are the same CHANGELOG section this call would have set.
  id=$(curl --max-time 300 -sSk "${auth[@]}" -H "Content-Type: application/json" \
    -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" '{tag_name:$t,name:$t,body:$b,prerelease:($t|test("-rc\\."))}')" \
    "$api/releases" | jq -r '.id // empty')
  if [ -z "$id" ]; then
    id=$(curl --max-time 30 --retry 3 --retry-connrefused --retry-max-time 90 -skf "${auth[@]}" \
      "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
  fi
  [ -n "$id" ] || { echo "could not create or find the release for $tag on $host" >&2; exit 1; }
fi
echo "release id on $host: $id"

for f in "$@"; do
  name=$(basename "$f")
  old=$(curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 -skf "${auth[@]}" "$api/releases/$id/assets" 2>/dev/null \
    | jq -r ".[] | select(.name==\"$name\") | .id" || true)
  # Delete-then-upload is a window where the asset does not exist, so the upload
  # MUST be checked. Without --fail curl exits 0 on an HTTP 4xx/5xx, and a
  # re-drive of a partial publish would delete the old asset, fail to replace it,
  # print "uploaded" and finish green — losing the artifact it was re-run to fix.
  if [ -n "$old" ]; then
    curl --max-time 300 -sk "${auth[@]}" -X DELETE "$api/releases/$id/assets/$old" >/dev/null || true
  fi
  if ! curl --max-time 300 -sSkf "${auth[@]}" \
      -X POST "$api/releases/$id/assets?name=$name" -F "attachment=@$f" >/dev/null; then
    echo "failed to upload $name to $host" >&2
    exit 1
  fi
  echo "  uploaded $name → $host"
done
