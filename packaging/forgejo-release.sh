#!/usr/bin/env bash
# Create (or reuse) a Forgejo/Gitea release and upload assets, idempotently.
#   forgejo-release.sh <host> <token> <tag> <notes-file> [asset...]
#
# Waits for the tag to exist first (push-mirrors can lag), so a release is never created against a
# missing tag. Same-named assets are immutable: a rerun accepts identical bytes, differing bytes fail
# and need a new tag, and nothing is ever deleted — so publishers targeting the same release in any
# order converge. Shared logic lives in release-common.sh; create + upload are forge-specific.
#
# Unlike GitHub, Forgejo stores the asset name verbatim, so no name normalisation happens here.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$here/release-common.sh"
# Named explicitly: this is the file a project writes when it adopts the standard, so its absence is
# a setup mistake someone is actively making, not a runtime fault. A raw "No such file" from the
# shell sends them reading this script instead of writing that one.
[ -f "$here/project.env" ] || {
  echo "missing $here/project.env — create it with PROJECT_REPO_SLUG=\"SisyphusMD/<project>\"" >&2
  exit 1
}
# shellcheck source=/dev/null
. "$here/project.env"

host="$1"; token="$2"; tag="$3"; notes_file="$4"; shift 4
api="https://$host/api/v1/repos/${PROJECT_REPO_SLUG:?project.env must set PROJECT_REPO_SLUG}"
auth=(-H "Authorization: token $token")
rel_validate_tag "$tag"

echo "waiting for tag $tag on $host..."
rel_wait_for_tag "$api/tags/$tag" || { echo "tag $tag never appeared on $host" >&2; exit 1; }

# A semver prerelease tag (contains a hyphen) is published as a prerelease so it never becomes the
# "latest" release.
pre=false; case "$tag" in *-*) pre=true ;; esac
id="$(rel_release_id "$api/releases" "$tag")"
if [ -z "$id" ]; then
  if created=$(curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -H "Content-Type: application/json" \
      -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" --argjson pre "$pre" \
            '{tag_name:$t,name:$t,body:$b,draft:false,prerelease:$pre}')" \
      "$api/releases"); then
    id=$(jq -r '.id // empty' <<<"$created")
  else
    # Another publisher can create the same release between the lookup above and this POST.
    id="$(rel_release_id "$api/releases" "$tag")"
  fi
fi
[ -n "$id" ] && [ "$id" != "null" ] || { echo "could not create/find release for $tag on $host" >&2; exit 1; }
rel_ensure_release_state "$api/releases/$id" "$pre" \
  || { echo "could not repair/verify release state for $tag on $host" >&2; exit 1; }
echo "release id on $host: $id"

upload_asset() {
  curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X POST "$api/releases/$id/assets?name=$2" \
    -F "attachment=@$1" >/dev/null
}

for f in "$@"; do
  [ -f "$f" ] && [ ! -L "$f" ] && [ -s "$f" ] \
    || { echo "release asset is missing, empty, non-regular, or symlinked: $f" >&2; exit 1; }
  name=$(basename "$f")
  if rel_asset_state "$api/releases/$id/assets" "$name" "$f"; then
    echo "  verified existing $name on $host"
    continue
  else
    state=$?
  fi
  case "$state" in
    # 12 is "could not ask" — fall through to the upload path, which re-checks before it writes.
    10|12) ;;
    11)
      [ "$REL_REPLACE_POLICY" = replace ] || { rel_reject_conflict "$name"; exit 1; }
      old=$(rel_asset_id "$api/releases/$id/assets" "$name")
      [ -n "$old" ] || { echo "cannot replace $name on $host: asset id not resolvable" >&2; exit 1; }
      curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X DELETE "$api/releases/$id/assets/$old" >/dev/null \
        || { echo "could not remove the superseded $name on $host" >&2; exit 1; }
      echo "  replacing $name on $host (REL_REPLACE_POLICY=replace)"
      ;;
    *) exit "$state" ;;
  esac
  rel_upload_verified "$api/releases/$id/assets" "$name" "$f" "$host" || exit 1
done
