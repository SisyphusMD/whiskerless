#!/usr/bin/env bash
# Delete every release candidate a shipped stable has superseded — releases, git tags, AND the
# apt/dnf packages — across the cluster Forgejo, NAS Forgejo, and GitHub registries.
#
#   prune-rcs.sh
#
# There is no version argument. The sweep enumerates every vX.Y.Z-rc.N across all three registries
# and the package repository, groups them by their stable stem vX.Y.Z, and deletes a group only once
# that stable is verified fully published everywhere. One script therefore serves both the automatic
# post-stable prune and an on-demand backlog sweep, and an rc whose stable has not shipped is kept —
# that is the point.
#
# Env: CLUSTER_TOKEN, NAS_TOKEN, GH_TOKEN, PACKAGE_TOKEN, DRY_RUN, STRICT. Stdlib shell + curl + jq
# only.
#
# Deletion is the one irreversible release operation, so it is gated hard:
#
#   * Per stem, the stable must be a PUBLISHED (non-draft, non-prerelease) release on all three
#     registries AND the three must serve an IDENTICAL, non-empty, duplicate-free asset-name set.
#     There is no fixed asset count to check against — an older stable legitimately serves fewer
#     assets than a current one — so cross-registry AGREEMENT is what proves the fan-out finished.
#   * A published RELEASE does not prove a published PACKAGE. The registry upload is a separate step
#     with its own failure modes, so the candidate must also be replaced everywhere it is currently
#     SERVED: same distributions, same architectures, read off the published index because that is
#     the only thing a user's package manager ever sees.
#   * Removal is VERIFIED per registry by re-reading live state, never by trusting a 204 or 404.
#   * Warn-only BY DEFAULT. A prune problem must never fail the release or make a valid stable
#     disappear, so every problem is reported and the sweep still exits 0. STRICT=true flips only the
#     reporting — a sweep that stopped early then exits 1 — for callers with no release to protect.
#   * Fail-closed throughout. Every "is it safe to delete" question answers "no" when it cannot be
#     answered at all, so an unreachable host is never mistaken for evidence.
#
# Removal is written against how the release-tag APIs actually behave, not how a naive stub pretends:
#
#   * A release and its git tag are two objects. Deleting the release leaves the git tag; deleting the
#     tag strands the release as an untagged draft that GET /releases/tags/<tag> then 404s for while
#     the LIST still shows it. So enumeration and verification read the LIST and the git refs, never
#     GET-by-tag, and the release id is captured during enumeration rather than looked up later.
#   * The release must be deleted BEFORE its tag: Forgejo 409s on deleting a tag that still has a
#     release attached, and a tag-first delete strands that untagged draft.
#   * The tag ref goes through the git-refs endpoint on all three. On Forgejo that leaves a stale tag
#     DB row the Releases UI still shows though every read API reports the tag gone; the plain
#     .../tags/<name> route clears it once no release is attached, so it is issued afterwards,
#     best-effort — the row is invisible to the read APIs and so can never be verified.
#   * Tags are never removed with `git push`: the cluster mirrors commits onward, and tag push churn
#     re-triggers the macOS workflows on old tags.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# For ignored_asset (release-common) over _IGNORED_ASSETS (asset-roles) — one definition of which
# assets sit outside the cross-registry quorum, shared with reconcile. extglob because the role
# patterns use `!(...)`. Sourced rather than reimplemented, and sourced at all because an undefined
# ignored_asset returns 127, the `||` beside it fires, every bottle counts toward the signature, the
# NAS never carries bottles, and the sweep then keeps every candidate forever while reporting success.
shopt -s extglob
# shellcheck source=/dev/null
. "$here/project.env"
# shellcheck source=/dev/null
. "$here/release-common.sh"
# shellcheck source=/dev/null
. "$here/asset-roles.sh"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"

# Missing credentials must not read as "nothing to prune". GitHub's releases are public, so an empty
# GH_TOKEN enumerates fine and only fails at the DELETE, after the other hosts have been swept.
: "${CLUSTER_TOKEN:?required}"
: "${NAS_TOKEN:?required}"
: "${GH_TOKEN:?required}"
# Forgejo scopes the package registry separately: `write:package`, which the repo tokens above do not
# carry. Required rather than optional, because an unset token would silently skip every package and
# report a clean sweep.
: "${PACKAGE_TOKEN:?required — write:package scope}"

# Fail CLOSED: only an exact "false" authorizes deletion. A `${DRY_RUN:-true}` default guards an
# UNSET value and nothing else — "True", "1", "yes", or an API dispatch that passed the input through
# unevaluated would all fall past a `= "true"` test and delete for real.
case "${DRY_RUN:-true}" in
  false) dry_run=false ;;
  *)     dry_run=true ;;
esac

# Fail SAFE here, the opposite default from DRY_RUN and for the opposite reason: this decides only how
# an unfinished sweep is REPORTED, never what it deletes. The automatic caller runs after a stable is
# already published on all three registries, where a non-zero exit reddens a release that succeeded
# and sends somebody hunting a publishing failure that did not happen. A manual dispatch has no
# release to protect and its operator needs the exit status to mean something, so it opts in.
case "${STRICT:-false}" in
  true) strict=true ;;
  *)    strict=false ;;
esac

# One classification for every way the sweep can conclude it must not continue. Whether a stop reddens
# the job is the caller's choice; that it stops rather than proceeds on a partial picture is not.
#
# The message names what already happened, because two of the stop sites sit INSIDE the deletion loop
# and are reached only after earlier stems are gone. Reporting "nothing pruned" there would describe
# an interrupted sweep as a no-op and hide the boundary a retry has to start from.
stop() {  # stop <what-went-wrong>
  # Residue counts as progress even though it is not a completed prune: reaching it means DELETEs were
  # already issued, so an operator told "nothing pruned" would look in the wrong place.
  local done_ok="${pruned:-0}" partial="${fail:-0}" progress="nothing pruned this run"
  if [ "$done_ok" -gt 0 ] || [ "$partial" -gt 0 ]; then
    progress="$done_ok rc tag(s) fully pruned and $partial left carrying residue before this point"
  fi
  if [ "$strict" = true ]; then
    echo "::error::prune: $1; $progress" >&2
    exit 1
  fi
  echo "::warning::prune: $1; $progress" >&2
  exit 0
}

REPO="$PROJECT_REPO_SLUG"
CLUSTER_HOST="forgejo.bryantserver.com"
NAS_HOST="forgejo.nas.bryantserver.com"
REGISTRIES=(cluster nas github)

# The apt/dnf package name. Derived from the slug rather than configured: a second source of truth
# for the same string is a second thing to get wrong, and every project here publishes its packages
# under its own repository name.
PKG_NAME="${REPO##*/}"
# The apt/dnf repositories are owner-scoped, not repo-scoped, and only the public instance serves
# them. TWO base URLs, and the difference is not cosmetic — see delete_package.
PKG_OWNER="${REPO%%/*}"
PKG_API="https://${CLUSTER_HOST}/api/v1/packages/${PKG_OWNER}"
REG="https://${CLUSTER_HOST}/api/packages/${PKG_OWNER}"
PKG_AUTH="Authorization: token ${PACKAGE_TOKEN}"

# Eventual consistency: a just-deleted release or tag can briefly still list, so verification is
# retried. The sleep is overridable (0 under test) so a stubbed run stays fast.
RETRY_ATTEMPTS=3
RETRY_SLEEP="${PRUNE_RETRY_SLEEP:-2}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

registry_releases_api() {
  case "$1" in
    cluster) printf 'https://%s/api/v1/repos/%s/releases' "$CLUSTER_HOST" "$REPO" ;;
    nas)     printf 'https://%s/api/v1/repos/%s/releases' "$NAS_HOST" "$REPO" ;;
    github)  printf 'https://api.github.com/repos/%s/releases' "$REPO" ;;
  esac
}

registry_tags_api() {
  case "$1" in
    cluster) printf 'https://%s/api/v1/repos/%s/tags' "$CLUSTER_HOST" "$REPO" ;;
    nas)     printf 'https://%s/api/v1/repos/%s/tags' "$NAS_HOST" "$REPO" ;;
    github)  printf 'https://api.github.com/repos/%s/tags' "$REPO" ;;
  esac
}

# The git tag (ref) endpoint, used for BOTH the DELETE and the verifying GET. Forgejo and GitHub
# agree on the git-refs shape, and the ref is the source of truth for verification.
registry_tag_ref_url() {
  case "$1" in
    cluster) printf 'https://%s/api/v1/repos/%s/git/refs/tags/%s' "$CLUSTER_HOST" "$REPO" "$2" ;;
    nas)     printf 'https://%s/api/v1/repos/%s/git/refs/tags/%s' "$NAS_HOST" "$REPO" "$2" ;;
    github)  printf 'https://api.github.com/repos/%s/git/refs/tags/%s' "$REPO" "$2" ;;
  esac
}

# Forgejo only: the plain .../tags/<name> route that clears the stale tag DB row a git-refs delete
# leaves behind. GitHub has no such split.
registry_tag_db_url() {
  case "$1" in
    cluster) printf 'https://%s/api/v1/repos/%s/tags/%s' "$CLUSTER_HOST" "$REPO" "$2" ;;
    nas)     printf 'https://%s/api/v1/repos/%s/tags/%s' "$NAS_HOST" "$REPO" "$2" ;;
  esac
}

registry_auth() {
  case "$1" in
    cluster) printf 'token %s' "$CLUSTER_TOKEN" ;;
    nas)     printf 'token %s' "$NAS_TOKEN" ;;
    github)  printf 'Bearer %s' "$GH_TOKEN" ;;
  esac
}

# Forgejo caps a listing with ?limit, GitHub with ?per_page.
registry_page_param() {
  case "$1" in
    github) printf 'per_page' ;;
    *)      printf 'limit' ;;
  esac
}

# A superseded rc tag: exactly the vX.Y.Z-rc.N grammar the workflows cut. Its stem is vX.Y.Z.
is_rc_tag() {
  [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$ ]]
}

# $1 registry, $2 url. Prints the body; empty on any transport error (fail-closed downstream).
http_get() {
  curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 180 \
    -sSL -H "Authorization: $(registry_auth "$1")" "$2" 2>/dev/null || true
}

# $1 registry, $2 url. Prints the body followed by a final line holding the HTTP status ("000" on a
# transport failure). Used where the status must gate interpretation: a JSON error body (a 401/403/5xx
# that still returns {"message":...}) must never be mistaken for a valid empty result.
http_get_status() {
  curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 180 \
    -sSL -w '\n%{http_code}' -H "Authorization: $(registry_auth "$1")" "$2" 2>/dev/null \
    || printf '\n000'
}

# $1 registry, $2 url. Issues the DELETE (a no-op under dry run). The returned HTTP code is NOT
# trusted — a 204 or 404 can lie — so every caller confirms removal by re-reading live state.
http_delete() {
  if [ "$dry_run" = true ]; then
    echo "  DRY-RUN would DELETE $2"
    return 0
  fi
  curl --max-time 120 -sS -X DELETE -H "Authorization: $(registry_auth "$1")" "$2" >/dev/null 2>&1 || true
  return 0
}

# Every tag name a registry knows, from BOTH the release listing and the git tag listing, paged.
#
# Both collections, because they fail apart: a publish that died before creating releases, or a sweep
# that removed releases and then failed on the tags, leaves tags with no release. Enumerating only
# the releases would strand those permanently — nothing else ever names them again.
#
# Prints `<tag>|<release-id>` for releases and `<tag>|` for bare tags. Returns nonzero if any page
# could not be read, so the caller can fail closed rather than sweep against a partial list.
list_registry_tags() {  # list_registry_tags <registry>
  local registry="$1" page param body kind api
  param="$(registry_page_param "$registry")"
  for kind in releases tags; do
    case "$kind" in
      releases) api="$(registry_releases_api "$registry")" ;;
      tags)     api="$(registry_tags_api "$registry")" ;;
    esac
    page=1
    while :; do
      body="$(http_get "$registry" "$api?$param=100&page=$page")"
      # An empty [] is a valid "nothing here". A non-array is a failed read, and treating it as end
      # of pages would sweep against a partial picture and still report success.
      jq -e 'type == "array"' <<<"$body" >/dev/null 2>&1 || return 1
      jq -e 'length > 0' <<<"$body" >/dev/null 2>&1 || break
      if [ "$kind" = releases ]; then
        jq -r '.[]? | [(.tag_name // ""), ((.id // "") | tostring)] | join("|")' <<<"$body" || return 1
      else
        jq -r '.[]? | [(.name // ""), ""] | join("|")' <<<"$body" || return 1
      fi
      page=$((page + 1))
    done
  done
}

# --- the apt/dnf registry half of the sweep ----------------------------------------------------
#
# Deleting an rc's release is only half the job: its .deb and .rpm keep being SERVED from the
# repositories until they are removed there too, so `apt-cache policy` goes on offering a candidate
# whose release page is gone, and `apt install` hands it to whoever asks. The endpoint asymmetry
# below was established against the LIVE registry rather than from the API docs, and is invisible at
# the API because every call returns 204 either way.

# A DELETE against the package registry. Dry-run aware like http_delete, but unlike it the status IS
# checked: the release path re-reads live state to confirm removal, and there is no equivalent cheap
# re-read for a registry version, so a refused delete has to surface here.
pkg_delete() {  # pkg_delete <url>
  local code
  if [ "$dry_run" = true ]; then
    echo "  DRY-RUN would DELETE $1"
    return 0
  fi
  code=$(curl --max-time 120 -sS -o /dev/null -w '%{http_code}' -X DELETE -H "$PKG_AUTH" "$1")
  case "$code" in
    20*|404) return 0 ;;
    *) echo "::error::DELETE $1 returned $code"; return 1 ;;
  esac
}

# Every apt/dnf package this project owns, as `<type> <registry-version>`.
#
# The two spellings differ and neither is guessable from the tag alone, so the registry is asked
# rather than told: debian keeps `0.2.0~rc.28`, while rpm appends its release and reports
# `0.2.0~rc.28-1`. Deleting by a constructed version 404s on rpm every time.
#
# Filtered by name as well as type: the delete is by version, and this owner also holds the sibling
# projects' packages and container images.
#
# Every failure is returned explicitly rather than left to `set -e`, which is off here: without the
# explicit returns a failed curl would leave an empty body, the filter would yield nothing, the loop
# would break and the function would report success — and the sweep would then delete releases while
# leaving the still-served packages behind, reporting a clean pass.
all_packages() {
  local page=1 body got names
  while :; do
    body=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 180 \
      -sSf -H "$PKG_AUTH" "$PKG_API?limit=100&page=$page") || return 1
    names=$(printf '%s' "$body" | jq -r '.[].name') || return 1
    [ -n "$names" ] || break
    got=$(printf '%s' "$body" | jq -r --arg name "$PKG_NAME" '
      .[] | select(.name == $name) | select(.type == "debian" or .type == "rpm")
      | "\(.type) \(.version)"') || return 1
    [ -z "$got" ] || printf '%s\n' "$got"
    page=$((page + 1))
  done
}

# `0.2.0~rc.28-1` (rpm) and `0.2.0~rc.28` (debian) both belong to tag `v0.2.0-rc.28`: drop rpm's
# trailing release, then undo the tilde that deb and rpm need in order to sort a candidate below its
# release.
pkg_tag() { printf 'v%s\n' "$(printf '%s' "$1" | sed -E 's/-[0-9]+$//; s/~rc\./-rc./')"; }

# The architectures a registry version actually carries, from its own file list.
arches_of() {  # arches_of <type> <version>
  curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf \
    -H "$PKG_AUTH" "$PKG_API/$1/$PKG_NAME/$2/files" | jq -r '.[].name' | while read -r n; do
      case "$1" in
        debian) n="${n##*_}"; printf '%s\n' "${n%.deb}" ;;
        rpm)    n="${n%.rpm}"; printf '%s\n' "${n##*.}" ;;
      esac
    done | sort -u
}

# Whether a version is being SERVED from a distribution — read off the published index, because that
# is the only thing a user's package manager ever sees. The registry listing says a version exists
# somewhere; it does not say it reached the distribution whose subscribers are about to lose the
# candidate.
#
# 0 = being served here, 1 = definitely not, 2 = could not tell. The third state is the point: `-sf`
# alone collapses "the index says no" and "the index did not load" into the same answer, and this
# guard's whole job is to keep a candidate alive until its replacement is demonstrably serving. A
# timeout must read as keep, never as prune.
index_has() {  # index_has <type> <distribution> <arch> <version>
  local url code body="$work/index-body"
  case "$1" in
    debian) url="$REG/debian/dists/$2/main/binary-$3/Packages" ;;
    rpm)    url="$REG/rpm/$2/repodata/primary.xml.gz" ;;
    *) return 2 ;;
  esac
  code=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 \
    -sS -o "$body" -w '%{http_code}' "$url") || return 2
  case "$code" in
    404) return 1 ;;   # nothing has ever been published to that index
    200) ;;
    *) return 2 ;;
  esac
  # Matched on NAME + ARCH + VERSION together, never version alone. Forgejo scopes the package
  # registry to the OWNER, so this repository holds the sibling project's packages too — and the two
  # release in lockstep, so "some package here is at 0.3.0" is routinely true while THIS package is
  # not. Version-only matching would report the stable as serving and license deleting a candidate
  # that is still the only installable copy.
  if [ "$1" = rpm ]; then
    # Decompressed to a file first, deliberately. Piping gunzip into grep loses gunzip's failure — a
    # truncated or corrupt index would come back as "no match", which the caller reads as "definitely
    # not served here" and treats as licence to delete. An index it cannot read has to stay unknown.
    gunzip -c "$body" > "$body.xml" 2>/dev/null || return 2
    # One <package> element at a time: name, arch and version must belong to the SAME entry. The rpm
    # index is not arch-scoped by URL the way the debian one is, so arch is checked here.
    awk -v n="$PKG_NAME" -v a="$3" -v v="${4%-*}" '
      BEGIN { RS = "<package" ; found = 0 }
      index($0, "<name>" n "</name>") \
        && index($0, "<arch>" a "</arch>") \
        && index($0, "ver=\"" v "\"") { found = 1 }
      END { exit !found }' "$body.xml"
  else
    # The debian index IS arch-scoped by URL (binary-<arch>), so only name and version are matched
    # here — but both, and within one stanza. Stanzas are blank-line separated.
    awk -v n="$PKG_NAME" -v v="$4" '
      BEGIN { RS = "" ; FS = "\n" ; found = 0 }
      {
        haveName = 0; haveVer = 0
        for (i = 1; i <= NF; i++) {
          if ($i == "Package: " n) haveName = 1
          if ($i == "Version: " v) haveVer = 1
        }
        if (haveName && haveVer) found = 1
      }
      END { exit !found }' "$body"
  fi
}

# Delete one registry version — and, just as importantly, get the repository metadata rebuilt so a
# package manager stops offering it.
#
# THE TWO FORMATS NEED OPPOSITE ENDPOINTS. This is not a style choice and not guessable; it was
# established against the live registry by deleting through each and reading the published index
# afterwards:
#
#   debian  the GENERIC endpoint rebuilds `dists/*/main/binary-*/Packages`; the pool endpoint
#           deletes the file and leaves the index advertising a version that now 404s.
#   rpm     the NATIVE endpoint rebuilds `repodata/`; the generic one deletes the file and leaves
#           `primary.xml` advertising it.
#
# Getting this backwards is invisible at the API — every call still returns 204 — and shows up only
# as a user being offered a version that cannot be downloaded.
delete_package() {  # delete_package <type> <version>
  local type="$1" version="$2" files arch dist
  case "$type" in
    debian)
      # One call takes every architecture and every distribution at once.
      pkg_delete "$PKG_API/debian/$PKG_NAME/$version" || return 1
      echo "        deleted debian $version"
      ;;
    rpm)
      # Per group and per architecture, so the architectures are read back off the version's own file
      # list rather than assumed. Both groups are tried because a 404 for one it never reached is
      # free, while missing the one it did reach leaves it being served.
      files=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf \
        -H "$PKG_AUTH" "$PKG_API/rpm/$PKG_NAME/$version/files" | jq -r '.[].name') || {
          echo "::error::could not list rpm files for $PKG_NAME $version"; return 1; }
      [ -n "$files" ] || { echo "::error::rpm $version reported no files"; return 1; }
      while read -r name; do
        [ -n "$name" ] || continue
        arch="${name%.rpm}"; arch="${arch##*.}"
        for dist in testing stable; do
          pkg_delete "$REG/rpm/$dist/package/$PKG_NAME/$version/$arch" || return 1
        done
        echo "        deleted rpm $version $arch"
      done <<< "$files"
      ;;
    *) echo "::error::unknown package type $type"; return 1 ;;
  esac
}

# $1 stem tag (vX.Y.Z). 0 only when the stable is a published release on all three registries AND the
# three serve an IDENTICAL, non-empty, duplicate-free asset-name set. A 200 alone is too weak a
# licence for a permanent delete: an interrupted publisher leaves a draft or misclassified prerelease
# that answers 200 and that nobody can install, and a half-fanned-out stable answers 200 on a registry
# serving fewer assets than its siblings. Either way the candidate is still the only complete copy.
#
# Returns 2 when a registry could not be read at all — not a keep decision but the absence of one.
#
# The stem's own tag and release are never pruned, so reading it GET-by-tag stays reliable here.
stable_present_everywhere() {
  local stem="$1" registry resp code json names signature="" have_signature=0 ok=1
  for registry in "${REGISTRIES[@]}"; do
    # http_get_status, not http_get: the STATUS has to gate the interpretation. A 401/403/5xx that
    # still returns {"message":...} is a non-empty body, so an emptiness check would pass it through
    # and the jq gate below would then report "not a published release" about a registry that was
    # never successfully read — the wrong sentence, in a one-shot sweep that never revisits it.
    resp="$(http_get_status "$registry" "$(registry_releases_api "$registry")/tags/$stem")"
    code="${resp##*$'\n'}"
    json="${resp%$'\n'*}"
    case "$code" in
      2[0-9][0-9]) ;;
      404)
        echo "::warning::prune: stable $stem is not published on $registry; keeping its rc" >&2
        ok=0; continue ;;
      *)
        echo "::error::prune: could not read $stem on $registry (HTTP $code) — refusing to conclude anything about it" >&2
        return 2 ;;
    esac
    # Present AND consumable: mirrors rel_ensure_release_state's draft==false && prerelease==false.
    if ! jq -e '(.id != null) and (.draft == false) and (.prerelease == false)' <<<"$json" >/dev/null 2>&1; then
      echo "::warning::prune: stable $stem is not a published (non-draft, non-prerelease) release on $registry; keeping its rc" >&2
      ok=0; continue
    fi
    # Non-empty and duplicate-free: a repeated name is the ambiguous copy reconcile refuses to treat
    # as usable, because its download URL is undefined.
    names="$(jq -r '
      [.assets[]?.name | select(. != null)] as $n
      | if ($n | length) > 0 and ($n | length) == ($n | unique | length)
        then $n | unique | join("\n")
        else error("empty or duplicated asset set")
        end' <<<"$json" 2>/dev/null)" \
      || { echo "::warning::prune: stable $stem does not serve a clean, non-empty asset set on $registry; keeping its rc" >&2
           ok=0; continue; }
    # Assets outside the quorum are dropped BEFORE the signature is built. Homebrew bottles reach
    # GitHub and the cluster Forgejo but never the NAS, by design — comparing raw sets would make
    # every bottled stable look permanently half-fanned-out and keep its candidates forever.
    names="$(while IFS= read -r _n; do
      [ -n "$_n" ] || continue
      ignored_asset "$_n" || printf '%s\n' "$_n"
    done <<<"$names")"
    [ -n "$names" ] || { echo "::warning::prune: stable $stem serves only ignored assets on $registry; keeping its rc" >&2
                         ok=0; continue; }
    # First qualifying registry sets the baseline; every other must match it byte for byte.
    if [ "$have_signature" -eq 0 ]; then
      signature="$names"; have_signature=1
    elif [ "$names" != "$signature" ]; then
      echo "::warning::prune: stable $stem serves a different asset set on $registry than another registry (partial fan-out); keeping its rc" >&2
      ok=0
    fi
  done
  [ "$ok" -eq 1 ]
}

# $1 registry, $2 id. 0 when no release with that id appears in the current LIST; nonzero if it still
# appears OR the list could not be re-read (an unreadable list is not proof of absence — fail closed).
# An empty id means this registry never listed a release for the rc, so there is nothing to remove.
release_absent() {
  local registry=$1 id=$2 body param page=1
  [ -n "$id" ] || return 0
  param="$(registry_page_param "$registry")"
  # Paged, like the enumeration. Reading only the first page would report a release "absent" as soon
  # as the repository holds more than one page of them — and absent is the answer that authorizes
  # deleting its tag, which is what strands the untagged draft this ordering exists to prevent.
  while :; do
    body="$(http_get "$registry" "$(registry_releases_api "$registry")?$param=100&page=$page")"
    jq -e 'type == "array"' <<<"$body" >/dev/null 2>&1 || return 1
    jq -e 'length > 0' <<<"$body" >/dev/null 2>&1 || return 0
    if jq -e --arg want "$id" 'any(.[]?; ((.id? // "") | tostring) == $want)' <<<"$body" >/dev/null 2>&1; then
      return 1
    fi
    page=$((page + 1))
  done
}

# $1 registry, $2 tag. 0 only when the git host AUTHORITATIVELY reports refs/tags/<tag> gone: a 404,
# or a 2xx read whose body contains no matching ref. Any other status — 000 transport failure, auth
# rejection, 5xx, or a JSON error body — is NOT proof of absence and fails closed, so a broken read is
# retried rather than mistaken for a completed prune.
tag_ref_absent() {
  local registry=$1 tag=$2 resp code body
  resp="$(http_get_status "$registry" "$(registry_tag_ref_url "$registry" "$tag")")"
  code="${resp##*$'\n'}"
  body="${resp%$'\n'*}"
  case "$code" in
    404) return 0 ;;
    2[0-9][0-9])
      jq -e --arg r "refs/tags/$tag" '
        (if type == "array" then .[] else . end) | select(.ref? == $r)
      ' <<<"$body" >/dev/null 2>&1 && return 1
      return 0 ;;
    *) return 1 ;;
  esac
}

# $1 registry, $2 tag, $3 id (may be empty where the registry lists no release for this rc, including
# an orphan tag a previous partial sweep left behind). Removes the rc and confirms it gone by
# RE-READING live state, retried for eventual consistency. The release is deleted and CONFIRMED absent
# from the LIST before its tag is touched at all, so a still-attached release is never turned into a
# stranded untagged draft. Returns 0 only once BOTH the release is gone from the list AND the git ref
# is gone.
remove_rc_on_registry() {
  local registry=$1 tag=$2 id=$3 attempt
  if [ "$dry_run" = true ]; then
    [ -n "$id" ] && http_delete "$registry" "$(registry_releases_api "$registry")/$id"
    http_delete "$registry" "$(registry_tag_ref_url "$registry" "$tag")"
    [ "$registry" != github ] && http_delete "$registry" "$(registry_tag_db_url "$registry" "$tag")"
    return 0
  fi
  for ((attempt = 1; attempt <= RETRY_ATTEMPTS; attempt++)); do
    if ! release_absent "$registry" "$id"; then
      [ -n "$id" ] && http_delete "$registry" "$(registry_releases_api "$registry")/$id"
    fi
    # ONLY once the release is verified absent is the now-orphaned tag ref removed. If the release
    # delete has not taken yet, the tag is deliberately left alone this pass and retried.
    if release_absent "$registry" "$id"; then
      if ! tag_ref_absent "$registry" "$tag"; then
        http_delete "$registry" "$(registry_tag_ref_url "$registry" "$tag")"
      fi
      if tag_ref_absent "$registry" "$tag"; then
        # Ref gone: clear Forgejo's stale tag DB row. The /tags/<name> route is reliable only once no
        # ref or release is attached, so it runs here. Best-effort — the row cannot be re-read to
        # confirm, and github has no such row.
        [ "$registry" != github ] && http_delete "$registry" "$(registry_tag_db_url "$registry" "$tag")"
        return 0
      fi
    fi
    [ "$attempt" -lt "$RETRY_ATTEMPTS" ] && sleep "$RETRY_SLEEP"
  done
  return 1
}

declare -A rc_id=()        # rc_id["<registry>|<tag>"] = that registry's release id for the rc
declare -A rc_tag_seen=()  # rc_tag_seen["<tag>"] = 1
declare -A stem_seen=()    # stem_seen["<stem>"] = 1

# Fail closed: a registry whose listings cannot be read makes the all-three view unreliable, so the
# sweep deletes nothing this run rather than enumerate a partial picture and orphan a copy.
for registry in "${REGISTRIES[@]}"; do
  if ! listing="$(list_registry_tags "$registry")"; then
    stop "could not read the release or tag listing on $registry"
  fi
  while IFS='|' read -r tname tid; do
    [ -n "$tname" ] || continue
    is_rc_tag "$tname" || continue
    rc_tag_seen["$tname"]=1
    stem_seen["${tname%-rc.*}"]=1
    [ -n "$tid" ] && rc_id["$registry|$tname"]="$tid"
  done <<< "$listing"
done

# Enumerated ONCE, before any deletion: an unreadable registry must stop the sweep rather than read
# as "this candidate published no packages", which would license deleting a release whose .deb is
# still being served.
all_packages > "$work/packages" || stop "could not enumerate the package registry"

# ALSO from the package registry, not only the listings. Releases are removed before packages, so a
# package DELETE that fails after its release is gone leaves an rc that no listing mentions and that a
# later sweep would never revisit, while apt goes on offering it. Enumerating the registry too makes
# that residue self-healing; the stable-replacement gate still has to pass before anything is deleted.
while read -r _ptype _pversion; do
  [ -n "$_pversion" ] || continue
  _ptag="$(pkg_tag "$_pversion")"
  is_rc_tag "$_ptag" || continue
  rc_tag_seen["$_ptag"]=1
  stem_seen["${_ptag%-rc.*}"]=1
done < "$work/packages"

if [ "${#stem_seen[@]}" -eq 0 ]; then
  echo "prune: no vX.Y.Z-rc.* releases, tags or packages found on any registry; nothing to prune"
  exit 0
fi

fail=0
pruned=0
# Candidates kept with no answer at all, as opposed to a definite answer of "not yet replaced".
# Counted apart from `fail` because nothing was deleted, and apart from an ordinary keep because a
# sweep that could not see is not a sweep that found nothing. Decided once per tag, at the keep site.
undetermined=0
while IFS= read -r stem; do
  [ -n "$stem" ] || continue
  stable_present_everywhere "$stem" || case $? in
    2) stop "a transport error interrupted checking whether $stem is published everywhere" ;;
    *) echo "prune: $stem is not fully published on all three registries; its rc releases are kept"
       continue ;;
  esac
  group_tags=()
  for tag in "${!rc_tag_seen[@]}"; do
    [ "${tag%-rc.*}" = "$stem" ] && group_tags+=("$tag")
  done
  [ "${#group_tags[@]}" -gt 0 ] || continue
  while IFS= read -r tag; do
    [ -n "$tag" ] || continue
    # A published RELEASE does not prove a published PACKAGE, and existing SOMEWHERE is not the test
    # either: the candidate must be replaced everywhere it is currently SERVED, same distributions
    # and same architectures.
    pkgs=""
    while read -r ptype pversion; do
      [ -n "$pversion" ] || continue
      [ "$(pkg_tag "$pversion")" = "$tag" ] && pkgs="$pkgs $ptype:$pversion"
    done < "$work/packages"
    missing_stable=""
    for entry in $pkgs; do
      ptype="${entry%%:*}"; pversion="${entry#*:}"
      sversion=""
      while read -r qtype qversion; do
        [ -n "$qversion" ] || continue
        if [ "$qtype" = "$ptype" ] && [ "$(pkg_tag "$qversion")" = "$stem" ]; then sversion="$qversion"; fi
      done < "$work/packages"
      if [ -z "$sversion" ]; then missing_stable="$missing_stable $ptype"; continue; fi
      # Captured, not iterated inline: bash discards the exit status of a command substitution in a
      # `for` word list, so a failed lookup would produce an empty list, skip every check below, and
      # license the delete this guard exists to prevent.
      if ! parches=$(arches_of "$ptype" "$pversion"); then
        stop "could not list $ptype files for $PKG_NAME $pversion"
      fi
      if ! sarches=$(arches_of "$ptype" "$sversion"); then
        stop "could not list $ptype files for $PKG_NAME $sversion"
      fi
      if [ -z "$parches" ]; then missing_stable="$missing_stable $ptype/no-files"; continue; fi
      for parch in $parches; do
        printf '%s\n' "$sarches" | grep -Fqx "$parch" \
          || missing_stable="$missing_stable $ptype/$parch"
        for pdist in testing stable; do
          if index_has "$ptype" "$pdist" "$parch" "$pversion"; then here_code=0; else here_code=$?; fi
          [ "$here_code" -eq 1 ] && continue          # candidate not served here
          if [ "$here_code" -eq 2 ]; then
            missing_stable="$missing_stable $ptype/$pdist(unreadable)"; continue
          fi
          # Both lookups are classified the same way. Collapsing "the stable is not here" and "I could
          # not ask" into one `||` reads the second as evidence of the first, which is how an
          # unreadable index becomes a confident "kept: no replacement" that nobody investigates.
          if index_has "$ptype" "$pdist" "$parch" "$sversion"; then there_code=0; else there_code=$?; fi
          if [ "$there_code" -eq 2 ]; then
            missing_stable="$missing_stable $ptype/$pdist(unreadable)"
          elif [ "$there_code" -ne 0 ]; then
            missing_stable="$missing_stable $ptype/$pdist"
          fi
        done
      done
    done
    if [ -n "$missing_stable" ]; then
      # Deduplicated: the checks run per architecture, so one missing distribution is otherwise
      # reported once for each.
      echo "keep: $tag — $stem does not yet replace it in:$(printf '%s' "$missing_stable" | tr ' ' '\n' | sort -u | tr '\n' ' ')"
      # Undetermined only when EVERY reason to keep was an unanswered question. One definite reason
      # settles the outcome on its own, and an unreadable index sitting beside it changed nothing —
      # counting that would redden a sweep whose decision was never in doubt, and a guard that cries
      # wolf is one an operator learns to skip.
      if ! printf '%s' "$missing_stable" | tr ' ' '\n' | grep -v '^$' | grep -qv '(unreadable)$'; then
        undetermined=$((undetermined + 1))
      fi
      continue
    fi

    if [ "$dry_run" = true ]; then
      echo "prune (dry-run): $tag superseded by stable $stem (present on all three); would remove release + git tag on each registry${pkgs:+ — packages:$pkgs}"
    else
      echo "prune: $tag superseded by stable $stem (present on all three); removing release + git tag"
    fi

    residue=""
    for registry in "${REGISTRIES[@]}"; do
      id="${rc_id[$registry|$tag]-}"
      if ! remove_rc_on_registry "$registry" "$tag" "$id"; then
        residue+="${residue:+, }$registry"
      fi
    done
    # AFTER the releases, and only for versions the registry actually reported. Of everything being
    # removed, the package is the one still being SERVED: a leftover release is clutter, a leftover
    # package keeps being offered by `apt upgrade`.
    if [ -z "$residue" ]; then
      for entry in $pkgs; do
        delete_package "${entry%%:*}" "${entry#*:}" \
          || residue+="${residue:+, }registry(${entry%%:*})"
      done
    fi
    if [ -n "$residue" ]; then
      # Both listings are enumerated, so residue of either shape — a surviving release or a
      # release-less orphan tag — is re-found and retried by a later sweep.
      echo "::warning::prune: $tag still has residue on: $residue (release, git tag and/or package survived delete+verify); a later sweep re-enumerates and retries it" >&2
      fail=$((fail + 1))
    elif [ "$dry_run" != true ]; then
      pruned=$((pruned + 1))
    fi
  done < <(printf '%s\n' "${group_tags[@]}" | sort)
done < <(printf '%s\n' "${!stem_seen[@]}" | sort)

# Two ways a completed sweep still owes the operator a non-zero answer under STRICT: tags it deleted
# but could not verify gone, and candidates it kept because an index would not answer. Neither is a
# reason to redden a release, so both stay warnings by default.
#
# A dry run reaches this too. Its whole purpose is to report the selection the real run would make,
# and a preview that could not read an index did not establish that selection — so the preview the
# manual dispatch runs BY DEFAULT must not come back green as though it had.
# Composed, not chosen between: the two counters describe different candidates, so reporting only the
# first would tell an operator about one tag's residue while silently dropping another tag whose
# safety was never established.
report=""
if [ "$fail" -gt 0 ]; then
  report="$fail rc tag(s) still carry residue on at least one registry; a later sweep re-enumerates and retries them"
fi
if [ "$undetermined" -gt 0 ]; then
  if [ -n "$report" ]; then report="$report; also "; fi
  report="${report}could not read a package index for $undetermined candidate(s), so they were kept with their safety unestablished"
fi

if [ -z "$report" ]; then
  if [ "$dry_run" = true ]; then
    echo "prune (dry-run): reported the selection above; no deletions issued"
  else
    echo "prune: $pruned superseded rc tag(s) removed and verified gone across all three registries"
  fi
  exit 0
fi
report="prune: $report"

if [ "$dry_run" = true ]; then
  report="$report (dry-run: no deletions were issued)"
fi
if [ "$strict" = true ]; then
  echo "::error::$report" >&2
  exit 1
fi
echo "::warning::$report" >&2
exit 0
