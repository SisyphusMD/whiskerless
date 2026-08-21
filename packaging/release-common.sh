#!/usr/bin/env bash
# Shared helpers for forgejo-release.sh + github-release.sh. Only the logic that is byte-identical
# between the two forges lives here: tag validation/waiting, release lookup, release-state repair,
# and immutable asset verification.
# Each caller keeps its own setup, release CREATE, and asset
# UPLOAD, because those genuinely differ (auth shape, endpoints, multipart vs data-binary upload).
# Sourced, not executed. Callers must have set an `auth` array (the curl -H args) before calling.
# $auth comes from the caller.
# shellcheck disable=SC2154

# Every curl below is time-bounded. An unreachable forge would otherwise hang with no deadline at
# all, stranding whichever release targets are sequenced after this one — Whiskerless lost a
# release's GitHub assets to exactly that. Reads retry because they are idempotent; MUTATIONS DO
# NOT, because a timed-out write may already have been applied and repeating it would duplicate
# rather than recover. Downloads get a wider ceiling: asset byte-comparison pulls the whole file,
# and these are tens of megabytes.
REL_READ=(--max-time 30 --retry 2 --retry-connrefused --retry-max-time 90)
REL_MUTATE=(--max-time 300)
REL_DOWNLOAD=(--max-time 600 --retry 2 --retry-connrefused --retry-max-time 900)

# REL_REPLACE_POLICY — "immutable" (default) or "replace".
#
# Immutable is the right default: a published name is a promise, and SHA256SUMS beside a silently
# swapped binary is worse than a failed publish. But it cannot be universal, because not every
# artifact is reproducible. Homebrew bottles are not, and Whiskerless deliberately keeps its bottle
# build dispatchable so ONE failed platform can be rebuilt without cutting a whole new candidate —
# a rebuild there necessarily produces different bytes, paired with a tap refresh that re-advertises
# the new checksums.
#
# So the policy is per-invocation and explicit. Only a caller that owns a documented rebuild-and-
# re-advertise path may set "replace", and it must do the re-advertising. Everything reproducible
# (sdist, .deb, .rpm, checksum manifests) stays immutable.
: "${REL_REPLACE_POLICY:=immutable}"

# rel_github_asset_name <local-basename> — the name GitHub will actually STORE.
#
# GitHub rewrites `~` to `.` in the stored name and enforces uniqueness on the rewritten form. A
# project whose artifacts carry a native package version (`foo_1.2.0~rc.3_amd64.deb`) therefore
# cannot look assets up by the local spelling: the lookup never matches what is already there, the
# uploader concludes the asset is absent, and the re-upload comes back 422 already_exists. Verified
# live: Forgejo stores `whiskerless_0.2.0~rc.34_amd64.deb`, GitHub stores `..._0.2.0.rc.34_...`.
# Bytes are still compared against the local file — only the NAME is normalised.
rel_github_asset_name() { printf '%s' "${1//\~/.}"; }

# rel_validate_tag <tag> — accept only the two tag shapes the release workflows can cut. Checked
# before any network call so a typo or a stray local tag can never address a release API.
rel_validate_tag() {
  [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] \
    || { echo "invalid release tag: $1" >&2; return 1; }
}

# rel_wait_for_tag <check-url> — poll until the tag exists (push-mirrors can lag before a release
# can be created against the tag). Uses the caller's $auth.
rel_wait_for_tag() {
  local _
  for _ in $(seq 1 60); do
    curl -sf --max-time 20 "${auth[@]}" "$1" >/dev/null && return 0
    sleep 10
  done
  return 1  # fail closed: the tag never appeared, so the caller must abort (not release blind)
}

# rel_release_id <releases-api> <tag> — print the existing release id for <tag>, or empty. Uses
# $auth. <releases-api> is the ".../releases" base; the by-tag lookup is "<base>/tags/<tag>".
rel_release_id() {
  curl -sf "${REL_READ[@]}" "${auth[@]}" "$1/tags/$2" 2>/dev/null | jq -r '.id // empty' || true
}

# rel_ensure_release_state <release-url> <expected-prerelease>
#
# The release may have been created by the other publisher or by a run that died mid-create, so its
# visibility and stable/prerelease classification are not implied by this run's create payload.
# Repair it, then read it back independently — a forge that accepts the PATCH but does not persist it
# must not be mistaken for a repaired release.
rel_ensure_release_state() {
  local url="$1" expected="$2" state payload
  state=$(curl -fsS "${REL_READ[@]}" "${auth[@]}" "$url") || return 1
  if jq -e --argjson expected "$expected" \
      '(.draft == false) and (.prerelease == $expected)' <<<"$state" >/dev/null; then
    return 0
  fi
  payload=$(jq -n --argjson expected "$expected" '{draft:false, prerelease:$expected}')
  curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X PATCH -H "Content-Type: application/json" \
    -d "$payload" "$url" >/dev/null || return 1
  state=$(curl -fsS "${REL_READ[@]}" "${auth[@]}" "$url") || return 1
  jq -e --argjson expected "$expected" \
    '(.draft == false) and (.prerelease == $expected)' <<<"$state" >/dev/null
}

# rel_asset_state <list-api> <name> <local-file>
#
#   0  the one existing same-named asset already holds identical bytes
#  10  absent
#  11  present but the bytes DIFFER — a content conflict
#   1  duplicate name, unreadable metadata, or a failed request
#
# 11 is separated from 1 so a caller can apply REL_REPLACE_POLICY to a genuine byte conflict without
# also swallowing an ambiguous or failed lookup. Nothing is deleted here in either case.
rel_asset_state() {
  local listing matches count url remote
  listing=$(curl -fsS "${REL_READ[@]}" "${auth[@]}" "$1") || return 1
  matches=$(jq -c --arg name "$2" '[.[] | select(.name==$name)]' <<<"$listing") || return 1
  count=$(jq -r 'length' <<<"$matches") || return 1
  case "$count" in
    0) return 10 ;;
    1) ;;
    # Two assets share the name, so which bytes a download URL serves is ambiguous.
    *) echo "release contains duplicate assets named $2" >&2; return 1 ;;
  esac
  url=$(jq -r '.[0].browser_download_url // empty' <<<"$matches")
  [ -n "$url" ] || { echo "release asset $2 has no download URL" >&2; return 1; }
  remote=$(mktemp)
  if ! curl -fsSL "${REL_DOWNLOAD[@]}" "${auth[@]}" -o "$remote" "$url"; then
    rm -f "$remote"
    return 1
  fi
  if cmp -s "$3" "$remote"; then
    rm -f "$remote"
    return 0
  fi
  rm -f "$remote"
  return 11
}

# rel_asset_id <list-api> <name> — print the id of the one asset called <name>, or empty.
rel_asset_id() {
  curl -fsS "${REL_READ[@]}" "${auth[@]}" "$1" 2>/dev/null \
    | jq -r --arg name "$2" 'map(select(.name==$name)) | if length == 1 then .[0].id else empty end' \
    || true
}

# rel_reject_conflict <name> — the immutable-policy failure message, in one place.
rel_reject_conflict() {
  echo "immutable release asset conflict for $1; publish different bytes under a new tag" >&2
  echo "  (set REL_REPLACE_POLICY=replace only from a documented rebuild path that also" >&2
  echo "   re-advertises the new checksums, e.g. a bottle rebuild paired with a tap refresh)" >&2
}

# rel_verify_uploaded_asset <list-api> <name> <local-file> — confirm the upload actually landed with
# the intended bytes. A 2xx upload is the forge's word; the readback is the evidence. Also settles
# the race where the other publisher uploaded the same asset concurrently.
rel_verify_uploaded_asset() {
  local _ status
  for _ in $(seq 1 6); do
    if rel_asset_state "$1" "$2" "$3"; then
      return 0
    else
      status=$?
    fi
    # 10 is "not visible yet" and worth another look; 11 (different bytes) and 1 are terminal.
    [ "$status" -eq 10 ] || return "$status"
    sleep 2
  done
  echo "uploaded release asset did not become visible: $2" >&2
  return 1
}

# ignored_asset <name> — an asset that is known, expected, and deliberately outside the
# cross-registry quorum. `_IGNORED_ASSETS` is per-project and comes from `asset-roles.sh`, which
# the caller must have sourced.
#
# Lives here rather than in reconcile because reconcile is not its only caller: prune compares
# each stable's asset-name set across all three registries, and an asset published to only two of
# them by design (a Homebrew bottle) made every bottled stable look permanently half-fanned-out,
# so its superseded candidates were never pruned at all.
ignored_asset() {
  local wanted="$1" pattern
  for pattern in "${_IGNORED_ASSETS[@]}"; do
    # shellcheck disable=SC2254 # $pattern is a deliberate glob, not a literal
    case "$wanted" in
      $pattern) return 0 ;;
    esac
  done
  return 1
}
