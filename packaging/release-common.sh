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
# release's GitHub assets to exactly that. Reads retry here because they are idempotent. Writes do
# NOT retry at this layer, because curl cannot tell a request that never landed from one that landed
# and lost its reply, and repeating the second duplicates rather than recovers. Retrying a write is
# therefore done one level up, in rel_upload_verified, which asks the forge what it holds before it
# writes again. Downloads get a wider ceiling: asset byte-comparison pulls the whole file, and these
# are tens of megabytes.
#
# curl's own --retry does not cover a connection reset mid-transfer, which is the shape these
# failures actually take. That is deliberately NOT patched with --retry-all-errors here: the layer
# above already recovers such a read (rel_asset_state reports 12, and its callers look again), and
# it recovers writes with a check-before-writing that curl cannot perform. Probing for the flag also
# means running curl at source time, which is a request in its own right.
REL_READ=(--max-time 30 --retry 3 --retry-connrefused --retry-max-time 120)
REL_MUTATE=(--max-time 300)
REL_DOWNLOAD=(--max-time 600 --retry 3 --retry-connrefused --retry-max-time 900)

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

# rel_read_json <url> — GET a JSON body under the retry profile, safely.
#
# curl cannot rewind a stdout it has already written to, so a response reset MID-body and then
# retried would emit the truncated first body followed by the whole second one, and the caller would
# parse the concatenation. Writing to a file lets curl truncate on each retry instead, which is the
# difference between a retry that heals the request and one that turns a dropped connection into a
# malformed-JSON error — the very failure the retries were added to remove.
rel_read_json() {
  local tmp rc=0
  tmp=$(mktemp) || return 1
  curl -fsS "${REL_READ[@]}" "${auth[@]}" -o "$tmp" "$1" || rc=$?
  [ "$rc" -eq 0 ] && cat "$tmp"
  rm -f "$tmp"
  return "$rc"
}

# rel_release_id <releases-api> <tag> — print the existing release id for <tag>, or empty. Uses
# $auth. <releases-api> is the ".../releases" base; the by-tag lookup is "<base>/tags/<tag>".
rel_release_id() {
  rel_read_json "$1/tags/$2" 2>/dev/null | jq -r '.id // empty' || true
}

# rel_ensure_release_state <release-url> <expected-prerelease>
#
# The release may have been created by the other publisher or by a run that died mid-create, so its
# visibility and stable/prerelease classification are not implied by this run's create payload.
# Repair it, then read it back independently — a forge that accepts the PATCH but does not persist it
# must not be mistaken for a repaired release.
rel_ensure_release_state() {
  local url="$1" expected="$2" state payload
  state=$(rel_read_json "$url") || return 1
  if jq -e --argjson expected "$expected" \
      '(.draft == false) and (.prerelease == $expected)' <<<"$state" >/dev/null; then
    return 0
  fi
  payload=$(jq -n --argjson expected "$expected" '{draft:false, prerelease:$expected}')
  curl -fsS "${REL_MUTATE[@]}" "${auth[@]}" -X PATCH -H "Content-Type: application/json" \
    -d "$payload" "$url" >/dev/null || return 1
  state=$(rel_read_json "$url") || return 1
  jq -e --argjson expected "$expected" \
    '(.draft == false) and (.prerelease == $expected)' <<<"$state" >/dev/null
}

# rel_asset_state <list-api> <name> <local-file>
#
#   0  the one existing same-named asset already holds identical bytes
#  10  absent
#  11  present but the bytes DIFFER — a content conflict
#  12  the forge could not be asked — the request itself failed
#   1  duplicate name or unreadable metadata
#
# 11 and 12 are separated from 1 because they license different responses: 11 is a verdict about the
# bytes and invites REL_REPLACE_POLICY, 12 is the absence of a verdict and invites another attempt,
# and 1 is ambiguous and invites neither. Folding 12 into 1 is what makes a dropped connection
# indistinguishable from a real conflict. Nothing is deleted here in any case.
rel_asset_state() {
  local listing matches count url remote
  listing=$(rel_read_json "$1") || return 12
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
    return 12
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
  rel_read_json "$1" 2>/dev/null \
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
    # 10 (not visible yet) and 12 (could not ask) are both worth another look; 11 and 1 are verdicts.
    [ "$status" -eq 10 ] || [ "$status" -eq 12 ] || return "$status"
    sleep 2
  done
  echo "uploaded release asset did not become visible: $2" >&2
  return 1
}

# rel_upload_verified <list-api> <name> <local-file> <label> — put the asset there and prove it.
#
# Uploads through the caller's `upload_asset <file> <name>`, and retries. A write is normally unsafe
# to repeat because a request that timed out may already have been applied, and repeating it would
# duplicate rather than recover. That is answered here by asking the forge what it actually holds
# before every attempt after the first: an upload whose connection broke AFTER the forge committed
# it is seen as already present and is not sent again, so the only thing a retry can do is finish an
# unfinished job. The readback also settles the race where a concurrent publisher wrote the same
# bytes first, which is indistinguishable from a rejected upload at the HTTP layer.
rel_upload_verified() {
  local list=$1 name=$2 file=$3 label=$4 attempt status
  for attempt in 1 2 3 4; do
    if [ "$attempt" -gt 1 ]; then sleep $(( (attempt - 1) * 5 )); fi
    # Nothing is written without a definite ABSENT verdict, on the first attempt as much as the
    # later ones. 12 is an unanswered question, not a licence to write: treating it as one is how a
    # write that already landed gets sent a second time, which is the duplication this exists to
    # prevent. Under REL_REPLACE_POLICY=replace the caller has already deleted the old asset, so an
    # 11 here is a delete that has not become visible yet and is worth another look rather than a
    # conflict to report.
    status=0; rel_asset_state "$list" "$name" "$file" || status=$?
    case "$status" in
      0)  echo "  $name already present and identical on $label"; return 0 ;;
      10) ;;
      12) continue ;;
      11)
        if [ "$REL_REPLACE_POLICY" = replace ]; then continue; fi
        rel_reject_conflict "$name"; return 1 ;;
      *)  return 1 ;;
    esac
    if upload_asset "$file" "$name"; then
      status=0; rel_verify_uploaded_asset "$list" "$name" "$file" || status=$?
      case "$status" in
        0)  echo "  uploaded immutable $name -> $label"; return 0 ;;
        11) rel_reject_conflict "$name"; return 1 ;;
      esac
    fi
  done
  echo "could not upload and verify $name on $label after 4 attempts" >&2
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
