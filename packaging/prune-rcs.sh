#!/usr/bin/env bash
# Delete every release candidate whose stable release has since shipped, on all
# three hosts — releases, tags, AND the apt/dnf packages. Driven by env, not
# arguments:
#   DRY_RUN=true|false (default true), GH_TOKEN, FORGEJO_TOKEN, NAS_TOKEN,
#   PACKAGE_TOKEN
#
# Idempotent and safe to re-run: candidates are enumerated from the REGISTRIES
# rather than from local git tags, so a sweep that deleted the tag but failed a
# later call still finds the leftovers next time. A group is deleted only once
# its stable exists on all three hosts, so a half-published stable can never
# strand its own candidates.
#
# The package registry is swept on the same terms and for a sharper reason than
# the releases are: a release nobody links to is only clutter, while a candidate
# left in the `testing` apt distribution is still being *served*, and anyone
# subscribed to it keeps being offered a version that was superseded and
# withdrawn everywhere else.
set -euo pipefail

# Missing credentials must not read as "nothing to prune". GitHub's releases are
# public, so an empty GH_TOKEN would enumerate fine and only fail at the DELETE,
# after the other hosts had already been swept.
: "${GH_TOKEN:?required}"
: "${FORGEJO_TOKEN:?required}"
: "${NAS_TOKEN:?required}"
# Forgejo scopes the package registry separately: `write:repository`, which every
# other call here uses, cannot read or delete a package. Required rather than
# optional, because an unset token would silently skip the packages and report a
# clean sweep.
: "${PACKAGE_TOKEN:?required}"
# Fail CLOSED: only an exact "false" authorizes deletion. `${DRY_RUN:-true}` guarded an UNSET
# value and nothing else — "True", "1", "yes", or an API dispatch that passed the input through
# unevaluated all fell past the `= "true"` tests below and deleted for real. Every legitimate
# caller already passes one of the two exact strings.
case "${DRY_RUN:-true}" in
  false) DRY_RUN=false ;;
  *)     DRY_RUN=true ;;
esac

# For ignored_asset (release-common.sh) over _IGNORED_ASSETS (asset-roles.sh) — ONE definition of
# which assets sit outside the cross-registry quorum, shared with reconcile. Sourced rather than
# reimplemented, and sourced at all because an undefined ignored_asset returns 127, the `||` beside
# it fires, every bottle counts toward the signature, the NAS never carries bottles, and the sweep
# then keeps every candidate forever while reporting success.
here="$(cd "$(dirname "$0")" && pwd)"
shopt -s extglob
# shellcheck source=/dev/null
. "$here/release-common.sh"
# shellcheck source=/dev/null
. "$here/asset-roles.sh"

# All three targets publish.yml releases to. Missing one would leave its objects
# behind while the sweep reported the rc pruned.
GH="https://api.github.com/repos/SisyphusMD/whiskerless"
FJ="https://forgejo.bryantserver.com/api/v1/repos/SisyphusMD/whiskerless"
NAS="https://forgejo.nas.bryantserver.com/api/v1/repos/SisyphusMD/whiskerless"
GH_AUTH="Authorization: Bearer ${GH_TOKEN}"
FJ_AUTH="Authorization: token ${FORGEJO_TOKEN}"
NAS_AUTH="Authorization: token ${NAS_TOKEN}"
# The apt/dnf repositories are owner-scoped, not repo-scoped, and only the public
# instance serves them (publish-registry.sh explains why the NAS does not).
#
# TWO base URLs, and the difference is not cosmetic. The generic API deletes a
# package version in one call, which is the tempting one — but on the RPM side it
# does NOT rebuild the group's repodata, so `primary.xml` keeps advertising a
# version whose file now 404s, and `dnf install` offers it and then fails to
# download it. Proven against the live registry, both ways. The registry-native
# endpoints are distribution- and architecture-aware and do regenerate, so those
# are what a sweep has to use.
PKG="https://forgejo.bryantserver.com/api/v1/packages/SisyphusMD"
REG="https://forgejo.bryantserver.com/api/packages/SisyphusMD"
PKG_AUTH="Authorization: token ${PACKAGE_TOKEN}"
# The one package name this project owns. Everything else under this owner —
# the container images the sister repos push, among others — must be invisible
# to a sweep that deletes by version.
PKG_NAME="whiskerless"

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
delete() {  # delete <url> <auth> [extra-acceptable-code]
  local code
  code=$(curl --max-time 120 -sS -o /dev/null -w '%{http_code}' -X DELETE -H "$2" "$1")
  case "$code" in
    20*|404) return 0 ;;
    "${3:-__none__}") return 0 ;;
    *) echo "::error::DELETE $1 returned $code"; return 1 ;;
  esac
}

# GitHub answers a DELETE for a ref that does not exist with 422 "Reference does
# not exist", not 404 — so the ordinary already-gone case reads as a hard error
# and aborts the sweep. That matters more now than it did: candidates are also
# enumerated from the package registry, which surfaces versions whose git tag was
# deleted by an earlier partial sweep and never existed to delete again.
delete_gh_ref() { delete "$1" "$2" 422; }

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

# Every apt/dnf package this project owns, as `<type> <registry-version> <tag>`.
#
# The two spellings differ and neither is guessable from the tag alone, so the
# registry is asked rather than told: debian keeps `0.2.0~rc.28`, while rpm
# appends its release and reports `0.2.0~rc.28-1`. Deleting by a constructed
# version 404s on rpm every time — checked against the live registry.
#
# Filtered by name as well as type: the delete is by version, and this owner also
# holds the sister projects' container images.
# Every failure is returned explicitly rather than relied on `set -e`: this is
# called on the left of `||`, which switches errexit off for everything inside
# it. Without the explicit returns a failed curl would leave an empty body, the
# filter would yield nothing, the loop would break and the function would report
# success — and the sweep would then delete releases and tags while leaving the
# still-served packages behind, reporting a clean pass.
all_packages() {
  local page=1 body got names
  while :; do
    body=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 180 \
      -sSf -H "$PKG_AUTH" "$PKG?limit=100&page=$page") || return 1
    names=$(printf '%s' "$body" | jq -r '.[].name') || return 1
    [ -n "$names" ] || break
    got=$(printf '%s' "$body" | jq -r --arg name "$PKG_NAME" '
      .[] | select(.name == $name) | select(.type == "debian" or .type == "rpm")
      | "\(.type) \(.version)"') || return 1
    [ -z "$got" ] || printf '%s\n' "$got"
    page=$((page + 1))
  done
}

# `0.2.0~rc.28-1` (rpm) and `0.2.0~rc.28` (debian) both belong to tag
# `v0.2.0-rc.28`: drop rpm's trailing release, then undo the tilde that deb and
# rpm need in order to sort a candidate below its release.
pkg_tag() { printf 'v%s\n' "$(printf '%s' "$1" | sed -E 's/-[0-9]+$//; s/~rc\./-rc./')"; }

# Delete one registry version — and, just as importantly, get the repository
# metadata rebuilt so a package manager stops offering it.
#
# THE TWO FORMATS NEED OPPOSITE ENDPOINTS. This is not a style choice and not
# guessable; it was established against the live registry by deleting through
# each and reading the published index afterwards:
#
#   debian  the GENERIC endpoint rebuilds `dists/*/main/binary-*/Packages`;
#           the pool endpoint deletes the file and leaves the index advertising
#           a version that now 404s.
#   rpm     the NATIVE endpoint rebuilds `repodata/`; the generic one deletes the
#           file and leaves `primary.xml` advertising it.
#
# Getting this backwards is invisible at the API — every call still returns 204 —
# and shows up only as a user being offered a version that cannot be downloaded.
# The architectures a registry version actually carries, from its own file list.
arches_of() {  # arches_of <type> <version>
  curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf \
    -H "$PKG_AUTH" "$PKG/$1/$PKG_NAME/$2/files" | jq -r '.[].name' | while read -r n; do
      case "$1" in
        debian) n="${n##*_}"; printf '%s\n' "${n%.deb}" ;;
        rpm)    n="${n%.rpm}"; printf '%s\n' "${n##*.}" ;;
      esac
    done | sort -u
}

# Whether a version is being SERVED from a distribution — read off the published
# index, because that is the only thing a user's package manager ever sees. The
# registry listing says a version exists somewhere; it does not say it reached
# the distribution whose subscribers are about to lose the candidate.
# 0 = being served here, 1 = definitely not, 2 = could not tell. The third state
# is the point: `-sf` alone collapses "the index says no" and "the index did not
# load" into the same answer, and this guard's whole job is to keep a candidate
# alive until its replacement is demonstrably serving. A timeout must read as
# keep, never as prune.
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
    # Decompressed to a file first, deliberately. Piping gunzip into grep loses
    # gunzip's failure — a truncated or corrupt index would come back as "no
    # match", which the caller reads as "definitely not served here" and treats
    # as licence to delete. An index it cannot read has to stay unknown.
    gunzip -c "$body" > "$body.xml" 2>/dev/null || return 2
    # One <package> element at a time: name, arch and version must belong to the SAME entry. The
    # rpm index is not arch-scoped by URL the way the debian one is, so arch is checked here.
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

delete_package() {  # delete_package <type> <version>
  local type="$1" version="$2" files arch dist
  case "$type" in
    debian)
      # One call takes every architecture and every distribution at once.
      delete "$PKG/debian/$PKG_NAME/$version" "$PKG_AUTH" || return 1
      echo "        deleted debian $version"
      ;;
    rpm)
      # Per group and per architecture, so the architectures are read back off
      # the version's own file list rather than assumed. Both groups are tried
      # because a 404 for one it never reached is free, while missing the one it
      # did reach leaves it being served — publish-registry.sh puts candidates in
      # `testing` only, but a sweep should not depend on that rule still holding.
      files=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf \
        -H "$PKG_AUTH" "$PKG/rpm/$PKG_NAME/$version/files" | jq -r '.[].name') || {
          echo "::error::could not list rpm files for $PKG_NAME $version"; return 1; }
      [ -n "$files" ] || { echo "::error::rpm $version reported no files"; return 1; }
      while read -r name; do
        [ -n "$name" ] || continue
        # whiskerless-0.2.0~rc.28-1.x86_64.rpm → x86_64
        arch="${name%.rpm}"; arch="${arch##*.}"
        for dist in testing stable; do
          delete "$REG/rpm/$dist/package/$PKG_NAME/$version/$arch" "$PKG_AUTH" || return 1
        done
        echo "        deleted rpm $version $arch"
      done <<< "$files"
      ;;
    *) echo "::error::unknown package type $type"; return 1 ;;
  esac
}

all_packages > "$work/packages" || { echo "::error::could not enumerate the package registry"; exit 1; }

{ all_tags "$GH" "$GH_AUTH" per_page releases
  all_tags "$FJ" "$FJ_AUTH" limit releases
  all_tags "$NAS" "$NAS_AUTH" limit releases
  all_tags "$GH" "$GH_AUTH" per_page tags
  all_tags "$FJ" "$FJ_AUTH" limit tags
  all_tags "$NAS" "$NAS_AUTH" limit tags
  # A previous sweep may have deleted the release and failed before the package,
  # leaving a candidate that is still being served and is named nowhere else.
  while read -r _type version; do
    [ -n "$version" ] && pkg_tag "$version"
  done < "$work/packages"
} | sort -u > "$work/all-tags"

rc=0
grep -E '^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$' "$work/all-tags" > "$work/rc-tags" || rc=$?
# grep exits 1 on no match, which is a legitimate empty result; any other status
# is a real failure.
[ "$rc" -le 1 ] || exit "$rc"

# 0 only when the stable is a PUBLISHED release on all three registries AND the three serve an
# IDENTICAL, non-empty, duplicate-free asset-name set. A 200 alone is too weak a licence for a
# permanent delete: an interrupted publisher leaves a draft or a misclassified prerelease that
# answers 200 and that nobody can install, and a half-fanned-out stable answers 200 on a registry
# serving fewer assets than its siblings. Either way the candidate is still the only complete copy.
#
# No fixed asset COUNT is assumed — a pre-.rpm-era stable legitimately serves fewer assets than a
# current one — so the test is agreement between registries, not a number. Ported from the sibling,
# which has carried it since its own retention policy landed.
stable_is_uniformly_published() {
  local stable="$1" pair url auth json names signature="" have_signature=0 ok=1
  for pair in "$GH|$GH_AUTH" "$FJ|$FJ_AUTH" "$NAS|$NAS_AUTH"; do
    url="${pair%%|*}"; auth="${pair#*|}"
    json="$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf \
              -H "$auth" "$url/releases/tags/$stable" 2>/dev/null)" || {
      # LOUD, and fatal, like the status probe above it. A timeout or 5xx here is not evidence
      # about the release — silently folding it into "keep" makes an infrastructure failure
      # indistinguishable from a stable that is legitimately still fanning out, and this sweep is
      # one-shot, so nothing revisits the decision. Refusing to conclude is the same answer the
      # neighbouring lookup gives for an unexpected status.
      echo "::error::prune: could not read $stable on $url — refusing to conclude anything about it" >&2
      return 2
    }
    # Present AND consumable: mirrors rel_ensure_release_state's draft==false && prerelease==false.
    if ! jq -e '(.id != null) and (.draft == false) and (.prerelease == false)' <<<"$json" >/dev/null 2>&1; then
      echo "::warning::prune: stable $stable is not a published release on $url; keeping its rc" >&2
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
      || { echo "::warning::prune: stable $stable serves no clean asset set on $url; keeping its rc" >&2
           ok=0; continue; }
    # Assets outside the quorum are dropped BEFORE the signature is built. Homebrew bottles reach
    # GitHub and the cluster Forgejo but never the NAS, by design — comparing raw sets would make
    # every bottled stable look permanently half-fanned-out and keep its candidates forever.
    names="$(while IFS= read -r _n; do
      [ -n "$_n" ] || continue
      ignored_asset "$_n" || printf '%s\n' "$_n"
    done <<<"$names")"
    [ -n "$names" ] || { echo "::warning::prune: stable $stable serves only ignored assets on $url; keeping its rc" >&2
                         ok=0; continue; }
    if [ "$have_signature" -eq 0 ]; then
      signature="$names"; have_signature=1
    elif [ "$names" != "$signature" ]; then
      echo "::warning::prune: stable $stable serves a different asset set on $url (partial fan-out); keeping its rc" >&2
      ok=0
    fi
  done
  [ "$ok" -eq 1 ]
}

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
  # 200 everywhere is necessary, not sufficient — see the helper above. Status 2 means a registry
  # could not be read at all, which is not a keep decision but an absence of one.
  stable_is_uniformly_published "$stable" || case $? in
    2) exit 1 ;;
    *) echo "keep    $tag — $stable is not uniformly published across the three registries"
       continue ;;
  esac
  # The registry versions this tag published, looked up rather than constructed.
  pkgs=""
  while read -r ptype pversion; do
    [ -n "$pversion" ] || continue
    [ "$(pkg_tag "$pversion")" = "$tag" ] && pkgs="$pkgs $ptype:$pversion"
  done < "$work/packages"

  # A published RELEASE does not prove a published PACKAGE. The registry upload is
  # a separate step with its own failure modes, and it deliberately runs even when
  # the release step went red — so a stable can exist on all three hosts while its
  # .deb and .rpm never reached the repository. Deleting the candidate then leaves
  # an apt subscriber with no installable version at all, which is worse than the
  # leftover this sweep exists to remove.
  #
  # Only the types this candidate actually has are required, so the candidates
  # that predate the repositories still prune on the release check alone.
  # Existing SOMEWHERE is not the test. The candidate must be replaced everywhere
  # it is currently being served: same distributions, same architectures. A stable
  # whose `testing` upload failed while `stable` succeeded still shows up in the
  # registry listing, and deleting the candidate on that evidence strands exactly
  # the testers the `testing` distribution exists for.
  missing_stable=""
  for entry in $pkgs; do
    ptype="${entry%%:*}"; pversion="${entry#*:}"
    sversion=""
    while read -r qtype qversion; do
      [ -n "$qversion" ] || continue
      if [ "$qtype" = "$ptype" ] && [ "$(pkg_tag "$qversion")" = "$stable" ]; then sversion="$qversion"; fi
    done < "$work/packages"
    if [ -z "$sversion" ]; then
      missing_stable="$missing_stable $ptype"
      continue
    fi
    # Captured, not iterated inline: bash discards the exit status of a command
    # substitution in a `for` word list, so a failed lookup would silently
    # produce an empty list, skip every check below, and license the delete this
    # guard exists to prevent.
    if ! parches=$(arches_of "$ptype" "$pversion"); then
      echo "::error::could not list $ptype files for $PKG_NAME $pversion"
      exit 1
    fi
    if ! sarches=$(arches_of "$ptype" "$sversion"); then
      echo "::error::could not list $ptype files for $PKG_NAME $sversion"
      exit 1
    fi
    if [ -z "$parches" ]; then
      missing_stable="$missing_stable $ptype/no-files"
      continue
    fi
    for parch in $parches; do
      printf '%s\n' "$sarches" | grep -Fqx "$parch" \
        || missing_stable="$missing_stable $ptype/$parch"
      for pdist in testing stable; do
        if index_has "$ptype" "$pdist" "$parch" "$pversion"; then
          here=0
        else
          here=$?
        fi
        [ "$here" -eq 1 ] && continue          # candidate not served here
        if [ "$here" -eq 2 ]; then
          missing_stable="$missing_stable $ptype/$pdist(unreadable)"
          continue
        fi
        if index_has "$ptype" "$pdist" "$parch" "$sversion"; then :; else
          missing_stable="$missing_stable $ptype/$pdist"
        fi
      done
    done
  done
  if [ -n "$missing_stable" ]; then
    # Deduplicated: the checks run per architecture, so one missing distribution
    # is otherwise reported once for each.
    echo "keep    $tag — $stable does not yet replace it in:$(printf '%s' "$missing_stable" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/^ */ /')"
    continue
  fi

  if [ "$DRY_RUN" = "true" ]; then
    echo "would prune $tag (superseded by $stable)${pkgs:+ — packages:$pkgs}"
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
  # Before the tags, and only for versions the registry actually reported. Any
  # failure above this line aborts the sweep, and of everything being deleted the
  # package is the one still being SERVED — a leftover release is clutter, a
  # leftover package keeps being offered by `apt upgrade`. One DELETE takes the
  # whole version: every architecture, and every distribution it went into, so
  # `testing` and `stable` need no separate calls.
  for entry in $pkgs; do
    delete_package "${entry%%:*}" "${entry#*:}"
  done
  delete_gh_ref "$GH/git/refs/tags/$tag" "$GH_AUTH"
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
