#!/usr/bin/env bash
# Create (or reuse) a Forgejo/Gitea release and upload assets, idempotently.
#   forgejo-release.sh <host> <token> <tag> <notes-file> [asset...]
#
# Waits for the tag to exist first (push-mirrors can lag), so a release is never
# created against a missing tag. Re-running replaces same-named assets, so the
# Forgejo (binary) and GitHub (.pkg) publishers can target the same release in
# any order.
set -euo pipefail

host="$1"; token="$2"; tag="$3"; notes_file="$4"; shift 4
api="https://$host/api/v1/repos/SisyphusMD/whiskerless"
auth=(-H "Authorization: token $token")

echo "waiting for tag $tag on $host…"
for _ in $(seq 1 60); do
  curl -skf "${auth[@]}" "$api/tags/$tag" >/dev/null && break
  sleep 10
done

id=$(curl -skf "${auth[@]}" "$api/releases/tags/$tag" 2>/dev/null | jq -r '.id // empty' || true)
if [ -z "$id" ]; then
  id=$(curl -sSk "${auth[@]}" -H "Content-Type: application/json" \
    -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" '{tag_name:$t,name:$t,body:$b}')" \
    "$api/releases" | jq -r .id)
fi
echo "release id on $host: $id"

for f in "$@"; do
  name=$(basename "$f")
  old=$(curl -skf "${auth[@]}" "$api/releases/$id/assets" 2>/dev/null \
    | jq -r ".[] | select(.name==\"$name\") | .id" || true)
  [ -n "$old" ] && curl -sk "${auth[@]}" -X DELETE "$api/releases/$id/assets/$old" >/dev/null || true
  curl -sSk "${auth[@]}" -X POST "$api/releases/$id/assets?name=$name" -F "attachment=@$f" >/dev/null
  echo "  uploaded $name → $host"
done
