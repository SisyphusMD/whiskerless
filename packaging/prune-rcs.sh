#!/usr/bin/env bash
# Delete every release candidate whose stable release has since shipped, on all
# three hosts. Driven by env, not arguments:
#   DRY_RUN=true|false (default true), GH_TOKEN, FORGEJO_TOKEN, NAS_TOKEN
#
# Idempotent and safe to re-run: candidates are enumerated from the REGISTRIES
# rather than from local git tags, so a sweep that deleted the tag but failed a
# later call still finds the leftovers next time. A group is deleted only once
# its stable exists on all three hosts, so a half-published stable can never
# strand its own candidates.
set -euo pipefail

# Missing credentials must not read as "nothing to prune". GitHub's releases are
# public, so an empty GH_TOKEN would enumerate fine and only fail at the DELETE,
# after the other hosts had already been swept.
: "${GH_TOKEN:?required}"
: "${FORGEJO_TOKEN:?required}"
: "${NAS_TOKEN:?required}"
DRY_RUN="${DRY_RUN:-true}"

# All three targets publish.yml releases to. Missing one would leave its objects
# behind while the sweep reported the rc pruned.
GH="https://api.github.com/repos/SisyphusMD/whiskerless"
FJ="https://forgejo.bryantserver.com/api/v1/repos/SisyphusMD/whiskerless"
NAS="https://forgejo.nas.bryantserver.com/api/v1/repos/SisyphusMD/whiskerless"
GH_AUTH="Authorization: Bearer ${GH_TOKEN}"
FJ_AUTH="Authorization: token ${FORGEJO_TOKEN}"
NAS_AUTH="Authorization: token ${NAS_TOKEN}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Every call is checked. A sweep that reports success while leaving a release or
# tag behind is worse than not running at all, because the next run's
# enumeration is what has to find it.
#
# Every curl is time-bounded, like the release helpers beside it: a host that
# accepts the connection and then stops responding would otherwise hang this
# job with no deadline, and a stable publish now waits on it. Reads retry;
# deletes do not, because a timed-out mutation may already have been applied.
status() {
  curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 \
    -sS -o /dev/null -w '%{http_code}' -H "$2" "$1"
}
delete() {
  local code
  code=$(curl --max-time 120 -sS -o /dev/null -w '%{http_code}' -X DELETE -H "$2" "$1")
  case "$code" in
    20*|404) return 0 ;;
    *) echo "::error::DELETE $1 returned $code"; return 1 ;;
  esac
}

# Union of what each registry actually holds, not what a checkout happens to
# know about — a previous partial sweep may have deleted the local tag while
# leaving remote objects behind. Paged, so the sweep does not quietly stop at
# 100 releases.
# Both surfaces: a publish that failed before creating releases, or a sweep that
# deleted releases and then failed on the tags, leaves tags with no release.
# Enumerating only /releases would strand those.
all_tags() {  # all_tags <api> <auth> <page-param> <collection>
  local page=1 body got
  while :; do
    # curl and jq failures must abort: treating a transient error as "end of
    # pages" would sweep against a partial list and still report success.
    body=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 180 \
      -sSf -H "$2" "$1/$4?$3=100&page=$page")
    got=$(printf '%s' "$body" | jq -r '.[] | .tag_name // .name')
    [ -n "$got" ] || break
    printf '%s\n' "$got"
    page=$((page + 1))
  done
}
{ all_tags "$GH" "$GH_AUTH" per_page releases
  all_tags "$FJ" "$FJ_AUTH" limit releases
  all_tags "$NAS" "$NAS_AUTH" limit releases
  all_tags "$GH" "$GH_AUTH" per_page tags
  all_tags "$FJ" "$FJ_AUTH" limit tags
  all_tags "$NAS" "$NAS_AUTH" limit tags
} | sort -u > "$work/all-tags"

rc=0
grep -E '^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$' "$work/all-tags" > "$work/rc-tags" || rc=$?
# grep exits 1 on no match, which is a legitimate empty result; any other status
# is a real failure.
[ "$rc" -le 1 ] || exit "$rc"

pruned=0
while read -r tag; do
  [ -n "$tag" ] || continue
  stable="${tag%-rc.*}"
  gh_stable=$(status "$GH/releases/tags/$stable" "$GH_AUTH")
  fj_stable=$(status "$FJ/releases/tags/$stable" "$FJ_AUTH")
  nas_stable=$(status "$NAS/releases/tags/$stable" "$NAS_AUTH")
  # Only a verified 404 means the stable is absent. A 5xx or a rate-limit would
  # otherwise read as "not published yet", and the sweep would keep every
  # candidate and still exit 0 — the automatic pass reporting success having
  # pruned nothing is exactly the silent failure this script is written against.
  for code in "$gh_stable" "$fj_stable" "$nas_stable"; do
    case "$code" in
      200|404) ;;
      *) echo "::error::stable lookup for $stable returned $code"; exit 1 ;;
    esac
  done
  if [ "$gh_stable$fj_stable$nas_stable" != "200200200" ]; then
    echo "keep    $tag — $stable not published everywhere" \
      "(gh=$gh_stable fj=$fj_stable nas=$nas_stable)"
    continue
  fi
  if [ "$DRY_RUN" = "true" ]; then
    echo "would prune $tag (superseded by $stable)"
    pruned=$((pruned + 1))
    continue
  fi
  echo "prune   $tag (superseded by $stable)"
  # Releases before tags: a bare tag is tidy, a release pointing at a tag that
  # no longer exists is not.
  # Only a verified 404 means "no release to delete". Anything else would orphan
  # a release behind its just-deleted tag.
  gh_code=$(status "$GH/releases/tags/$tag" "$GH_AUTH")
  case "$gh_code" in
    200)
      gh_id=$(curl --max-time 30 --retry 2 --retry-connrefused --retry-max-time 90 \
        -sSf -H "$GH_AUTH" "$GH/releases/tags/$tag" | jq -re '.id')
      delete "$GH/releases/$gh_id" "$GH_AUTH"
      ;;
    404) ;;
    *) echo "::error::GET $GH/releases/tags/$tag returned $gh_code"; exit 1 ;;
  esac
  delete "$FJ/releases/tags/$tag" "$FJ_AUTH"
  delete "$NAS/releases/tags/$tag" "$NAS_AUTH"
  delete "$GH/git/refs/tags/$tag" "$GH_AUTH"
  delete "$FJ/tags/$tag" "$FJ_AUTH"
  delete "$NAS/tags/$tag" "$NAS_AUTH"
  pruned=$((pruned + 1))
done < "$work/rc-tags"

echo "---"
if [ "$DRY_RUN" = "true" ]; then
  echo "$pruned release candidate(s) would be pruned"
else
  echo "$pruned release candidate(s) pruned"
fi
