#!/usr/bin/env bash
# Create (or reuse) a GitHub release and upload assets, idempotently.
#   github-release.sh <token> <tag> <notes-file> [asset...]
#
# Mirror of forgejo-release.sh for the GitHub API. Both publishers pass the SAME CHANGELOG notes, so
# whoever creates the release first sets identical notes and the other just appends its asset.
# Shared wait/lookup/state/verify logic lives in release-common.sh; GitHub's asset upload uses a
# separate host and data-binary, so it stays here.
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

token="${1:?a GitHub token is required; this must never call GitHub unauthenticated}"
tag="$2"; notes_file="$3"; shift 3
repo="${PROJECT_REPO_SLUG:?project.env must set PROJECT_REPO_SLUG}"
api="https://api.github.com/repos/$repo"
auth=(-H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json")
rel_validate_tag "$tag"


# The tag must exist before the release is created. Using the SINGULAR, exact `git/ref/` endpoint:
# the plural `git/refs/` form is a PREFIX match, so waiting for `v0.2.0` is satisfied by an existing
# `v0.2.0-rc.1` and the wait returns immediately for a tag that does not exist. The release POST
# below sends no target_commitish, so GitHub would then mint that tag from the default branch.
echo "waiting for tag $tag on GitHub..."
rel_wait_for_tag "$api/git/ref/tags/$tag" || { echo "tag $tag never appeared on GitHub" >&2; exit 1; }

# A semver prerelease tag (contains a hyphen) is published as a prerelease so it never becomes
# GitHub's "latest" release.
pre=false; case "$tag" in *-*) pre=true ;; esac
id="$(rel_release_id "$api/releases" "$tag")"
if [ -z "$id" ]; then
  if created=$(curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X POST "$api/releases" \
      -d "$(jq -n --arg t "$tag" --rawfile b "$notes_file" --argjson pre "$pre" \
            '{tag_name:$t,name:$t,body:$b,draft:false,prerelease:$pre}')"); then
    id=$(jq -r '.id // empty' <<<"$created")
  else
    # Another publisher can create the same release between the lookup above and this POST.
    id="$(rel_release_id "$api/releases" "$tag")"
  fi
fi
[ -n "$id" ] && [ "$id" != "null" ] || { echo "could not create/find GitHub release for $tag" >&2; exit 1; }
rel_ensure_release_state "$api/releases/$id" "$pre" \
  || { echo "could not repair/verify GitHub release state for $tag" >&2; exit 1; }
echo "GitHub release id: $id"

upload_asset() {
  curl -fsS "${REL_MUTATE[@]}" -H "Authorization: Bearer $token" \
    -H "Content-Type: application/octet-stream" --data-binary @"$1" \
    "https://uploads.github.com/repos/$repo/releases/$id/assets?name=$2" >/dev/null
}

for f in "$@"; do
  [ -f "$f" ] && [ ! -L "$f" ] && [ -s "$f" ] \
    || { echo "release asset is missing, empty, non-regular, or symlinked: $f" >&2; exit 1; }
  name=$(rel_github_asset_name "$(basename "$f")")
  if rel_asset_state "$api/releases/$id/assets" "$name" "$f"; then
    echo "  verified existing $name on GitHub"
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
      [ -n "$old" ] || { echo "cannot replace $name on GitHub: asset id not resolvable" >&2; exit 1; }
      # `/releases/assets/{asset_id}` — the asset id is global and GitHub's DELETE does NOT take the
      # release id, even though the LIST endpoint beside it does. Addressed the natural-looking way
      # it 404s, the delete becomes a silent no-op, and the re-upload then hits 422 already_exists.
      curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X DELETE "$api/releases/assets/$old" >/dev/null \
        || { echo "could not remove the superseded $name on GitHub" >&2; exit 1; }
      echo "  replacing $name on GitHub (REL_REPLACE_POLICY=replace)"
      ;;
    *) exit "$state" ;;
  esac
  rel_upload_verified "$api/releases/$id/assets" "$name" "$f" "GitHub" || exit 1
done
