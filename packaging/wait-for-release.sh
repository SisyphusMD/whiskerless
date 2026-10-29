#!/usr/bin/env bash
# Block until a release is genuinely installable, then return.
#   wait-for-release.sh <tag>        e.g. v1.4.0-rc.2
#
# One definition, called by BOTH install matrices — the Linux one on Forgejo and
# the macOS one on GitHub. They start from the same tag push and would otherwise
# each carry their own idea of "ready", which is the kind of drift that leaves one
# forge testing a half-published release and reporting success.
#
# "Installable" is three things, and the second is the one that bites:
#
#   1. The release carries every artifact. The .pkg and the bottles are built by
#      separate workflows and arrive minutes apart, so this waits for the slowest.
#      What to wait FOR is not written down twice: it reads packaging/asset-roles.sh,
#      the same table reconcile-releases.sh replicates, so a new artifact is added
#      in one place and both learn about it.
#
#   2. The TAP advertises the checksums the release is serving RIGHT NOW. Bottle
#      legs install from the tap, and the tap is written in two passes: the
#      formula lands as soon as PyPI has the sdist, the `bottle do` block only
#      once the bottles exist. A leg let through between them installs the right
#      version by BUILDING it from source. Worse, a bottle REBUILD replaces the
#      archives under an unchanged tag, so a tag-shaped check would pass instantly
#      while the tap still advertised the replaced bytes — the state that once
#      broke `brew install` for everyone.
#
#   3. The apt/dnf REGISTRY serves this version. The matrix installs from those
#      repositories, and registry publishing is a separate job that waits for BOTH
#      architectures to land — arm64 is built on the other forge now — so it can
#      finish after the bottles. It used to be a step of the release job, which
#      ordered it ahead of everything here by accident rather than by design.
#      Without this, a healthy release gets a red apt-repo leg for having been
#      asked too early.
#
# Everything project-specific comes from packaging/project.env and
# packaging/asset-roles.sh, so this file itself is the same in every project.
set -euo pipefail

TAG="${1:?usage: $0 <tag>}"
case "$TAG" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "::error::not a release tag: $TAG" >&2; exit 1 ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"
[ -f "$here/project.env" ] || { echo "$0: packaging/project.env is missing" >&2; exit 2; }
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
: "${PROJECT_TAP_SLUG:?project.env must define PROJECT_TAP_SLUG}"

shopt -s extglob
# For ignored_asset, over the _IGNORED_ASSETS table asset-roles.sh declares.
# shellcheck source=/dev/null
. "$here/release-common.sh"
# shellcheck source=/dev/null
. "$here/asset-roles.sh"

# A base URL with its scheme, which is how every workflow and script spells FORGE.
# A bare host is refused rather than patched up: tolerating a second spelling here is how the callers
# drifted into two conventions in the first place, and curl would read a bare host as plain http.
FORGE="${FORGE:-https://forgejo.bryantserver.com}"
case "$FORGE" in
  https://?*) FORGE="${FORGE%/}" ;;
  *) echo "::error::FORGE must be a base URL such as https://forgejo.example.com, not: $FORGE" >&2; exit 2 ;;
esac
API="$FORGE/api/v1/repos/$PROJECT_REPO_SLUG/releases/tags/$TAG"
# 300 x 30s = 150 minutes, and the number comes from the chain this waits on rather than from
# taste. The bottles cannot start until publish.yml has proven the formula installs and pushed the
# first tap pass, which builds from source; build-bottles.sh will itself wait up to 90 minutes for
# that, and the bottle build then takes about half an hour before the second pass lands them on the
# release. The macOS .pkg meanwhile signs and notarizes through Apple's queue rather than ours. A
# budget under the sum of those does not test a slow release, it fails one. Overridable so a
# dispatch against an already-complete tag need not carry the full deadline.
ATTEMPTS="${WAIT_ATTEMPTS:-300}"
INTERVAL="${WAIT_INTERVAL:-30}"

# The package, the formula and the registry entry all carry the repository's name.
OWNER="${PROJECT_REPO_SLUG%%/*}"
PKG="${PROJECT_REPO_SLUG#*/}"
# A candidate writes only the -rc formula; a stable tag writes both, and the stable formula is the
# one a stable install pours.
case "$TAG" in
  *-rc.*) FORMULA="$PKG-rc" ;;
  *)      FORMULA="$PKG" ;;
esac

# Bounded, always. The attempt count only bounds this if each request is bounded
# too — a connection that is accepted and then stalls would otherwise hang past
# it, to whatever the runner's own timeout is.
# Forge-only, too: GitHub is reached solely through github_ready, which authenticates, and a URL
# taken from release JSON must not be able to route an unauthenticated request anywhere else.
fetch() {
  case "$1" in
    "$FORGE"/*) : ;;
    *) echo "  fetch: refusing a URL outside $FORGE: $1" >&2; return 1 ;;
  esac
  # No -L: Forgejo serves assets directly, and a followed redirect would leave $FORGE unchecked.
  curl -sf --connect-timeout 10 --max-time 60 --retry 2 --retry-connrefused "$FORGE/${1#"$FORGE"/}"
}

# The registry versions publish-registry.sh writes: debian keeps the native `~rc.`
# form, and rpm carries nfpm's release suffix. Derived the same way there, so the
# two move together if that suffix ever changes.
PKGVER="${TAG#v}"; PKGVER="${PKGVER/-rc./~rc.}"
PKGAPI="$FORGE/api/v1/packages/$OWNER"

# Scope: this answers "has the registry been written yet", not "is the release good". A
# distribution whose upload FAILED already fails publish-registry.sh, which exits non-zero and
# reddens its job — a red apt-repo leg there is a correct report, not the premature one this
# guards against.
registry_ready() {
  local kind ver a b
  for kind in debian rpm; do
    # BOTH architectures, by filename. A non-empty list is not enough: the two are
    # uploaded one after the other, so a poll landing between them would release
    # the arm64 legs against a repository that only has amd64 — and that fails
    # deterministically on a retry after a partial publish, not just rarely.
    case "$kind" in
      debian) ver="$PKGVER";    a="_amd64.deb";  b="_arm64.deb" ;;
      rpm)    ver="$PKGVER-1";  a=".x86_64.rpm"; b=".aarch64.rpm" ;;
    esac
    # `fetch` carries curl's -f, and that is load-bearing rather than tidiness.
    # Without it a 404 still writes its JSON error object to stdout and jq would
    # be reading that object instead of a file list. Verified against this
    # registry, as were the two version spellings above.
    fetch "$PKGAPI/$kind/$PKG/$ver/files" 2>/dev/null \
      | jq -e --arg a "$a" --arg b "$b" \
          '[.[].name] | any(endswith($a)) and any(endswith($b))' >/dev/null 2>&1 || return 1
  done
}

tap_ready() {  # tap_ready <release-json>
  local rel="$1" rb want have
  rb=$(fetch "$FORGE/$PROJECT_TAP_SLUG/raw/branch/main/Formula/$FORMULA.rb") || return 1
  # Fixed-string and including the closing quote: unanchored, rc.2 is a prefix of
  # rc.28 and matches its root_url.
  printf '%s\n' "$rb" | grep -qF "releases/download/${TAG}\"" || return 1
  have=$(printf '%s\n' "$rb" | awk '/^ *bottle do$/,/^ *end$/' \
           | sed -n 's/.*"\([0-9a-f]\{64\}\)".*/\1/p' | LC_ALL=C sort -u)
  # The outer manifest key is tap-qualified; `formula.name` is the short name,
  # which is what tells a stable release's two sets of bottles apart.
  want=$(printf '%s\n' "$rel" \
           | jq -r '.assets[]? | select(.name | endswith(".bottle.json")) | .browser_download_url' \
           | while read -r u; do
               [ -n "$u" ] || continue
               fetch "$u" | jq -r --arg f "$FORMULA" \
                 '.[] | select(.formula.name == $f) | .bottle.tags[].sha256'
             done | LC_ALL=C sort -u)
  [ -n "$want" ] && [ "$want" = "$have" ]
}

# The matrix's deb-file-github channel downloads from GitHub, not from this forge, so a release
# whose GitHub upload failed is NOT installable however complete it looks here. That gap used to be
# covered by accident: the handoff waited on reconcile, which heals the mirrors, so GitHub had been
# repaired by dispatch time. The handoff no longer waits — reconcile's full-history sweep is not
# worth the critical path — so readiness now states directly what the ordering used to imply.
#
# Checked only after everything local passes, which keeps it off the polling hot path: a handful of
# calls on a healthy release, and repeated only while a repair is genuinely in flight. That rate is
# REQUIRED: unauthenticated github.com allows 60 requests an hour per IP and every runner
# shares one, so an unauthenticated poll answers 403 instead of answering.
github_ready() {
  local auth names code body
  auth=(-H "Authorization: Bearer ${GITHUB_ASSET_TOKEN}")
  body="$(mktemp)"
  code="$(curl -sS -o "$body" -w '%{http_code}' --max-time 60 "${auth[@]}" \
    -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/$PROJECT_REPO_SLUG/releases/tags/$TAG" || echo 000)"
  # A throttled read is NOT an absent asset, and reporting it as one turns a quota problem into
  # "the release never became installable" — a diagnosis pointing at the wrong system entirely.
  case "$code" in
    403|429) echo "  GitHub rate-limited the readiness check (HTTP $code); still waiting" ;;
  esac
  # `.state`, not just `.name`. GitHub keeps the asset RECORD when an upload dies partway, in state
  # "starter" rather than "uploaded" — and a name-only match would accept that record and release the
  # matrix against a download that still 404s, which is the precise failure this check exists to stop.
  names="$(jq -r '.assets[]? | select(.state == "uploaded") | .name' < "$body" 2>/dev/null || true)"
  rm -f "$body"
  [ "$code" = 200 ] || return 1
  [ -n "$names" ] || return 1
  # No version match needed: the query is already scoped to this tag's release, so any .deb under
  # it is this tag's. Both arches, because they upload one after the other and a poll landing
  # between them would release the arm64 legs against a GitHub release that only has amd64.
  printf '%s\n' "$names" | grep -q -- "_amd64.deb$" && \
  printf '%s\n' "$names" | grep -q -- "_arm64.deb$"
}

# Spaced on its own cadence, not the loop's, and sized to the authenticated ceiling of
# 5,000/hour — the only one that applies, since this refuses to poll unauthenticated.
: "${GITHUB_ASSET_TOKEN:?a GitHub token is required; this must never poll GitHub unauthenticated}"
GH_INTERVAL="${GH_WAIT_INTERVAL:-20}"

# Roles a release may predate. A dispatch deliberately runs the CURRENT scripts against an OLDER
# tag — that is the whole point of the tag input — and releases cut before a role existed do not
# carry it. Demanding it would make such a dispatch wait out its full deadline and then fail for a
# release that is perfectly complete. Optional roles are still all-or-nothing: a release carrying
# ANY of them was cut after they existed, so the rest are merely late — the per-architecture
# checksums upload from two machines, and a poll between them must not pass. A release carrying none
# of them is excused only if it carries what preceded them, when asset-roles.sh names a predecessor.
# Read through `${a[@]+...}` because either table may be empty, and an empty array is unbound under
# `set -u` in the bash 3.2 a macOS runner may still resolve.
optional_asset_role() {  # optional_asset_role <role>
  local role
  for role in ${_OPTIONAL_ASSET_ROLES[@]+"${_OPTIONAL_ASSET_ROLES[@]}"}; do
    [ "$1" = "$role" ] && return 0
  done
  return 1
}
for _role in ${_OPTIONAL_ASSET_ROLES[@]+"${_OPTIONAL_ASSET_ROLES[@]}"}; do
  _known=""
  for _r in "${_ASSET_ROLES[@]}"; do [ "$_r" = "$_role" ] && _known=1; done
  # An optional role outside the role table would never be consulted, and the check it was meant to
  # relax would silently be the full one — or, for a typo, would silently not exist.
  [ -n "$_known" ] || { echo "$0: optional role '$_role' is not in _ASSET_ROLES" >&2; exit 2; }
done
unset _role _r _known

# Roles a project no longer builds, which reconcile must still heal on the old releases that carry
# them but which no new release will ever carry: the Intel .pkg, once Intel Macs were dropped. The
# wait never demands one. Optional does not fit, because an optional role is late until it arrives,
# and the first release cut after dropping Intel waited out its whole deadline, in both projects,
# for a .pkg nothing would build.
retired_asset_role() {  # retired_asset_role <role>
  local role
  for role in ${_RETIRED_ASSET_ROLES[@]+"${_RETIRED_ASSET_ROLES[@]}"}; do
    [ "$1" = "$role" ] && return 0
  done
  return 1
}
for _role in ${_RETIRED_ASSET_ROLES[@]+"${_RETIRED_ASSET_ROLES[@]}"}; do
  _known=""
  for _r in "${_ASSET_ROLES[@]}"; do [ "$_r" = "$_role" ] && _known=1; done
  [ -n "$_known" ] || { echo "$0: retired role '$_role' is not in _ASSET_ROLES" >&2; exit 2; }
  ! optional_asset_role "$_role" || { echo "$0: role '$_role' is both optional and retired" >&2; exit 2; }
done
unset _role _r _known

carries() {  # carries <asset-names> <glob>
  local name
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    # Ignored assets never satisfy a role. A bottle is `<pkg>-<version>.<platform>.bottle.tar.gz`,
    # which an arch-independent source-tarball glob matches — so a release whose source tarball
    # had not replicated yet looked ready, and the source-install legs started and 404'd instead
    # of waiting. Same filter reconcile applies, from the same table.
    ignored_asset "$name" && continue
    # shellcheck disable=SC2254 # $2 is a deliberate glob, not a literal
    case "$name" in
      $2) return 0 ;;
    esac
  done <<<"$1"
  return 1
}

# Which roles this release does not carry yet. Named, not just counted: a silent poll that ends in
# "never became installable" says nothing about WHICH artifact never arrived, and that is the one
# fact needed to tell a slow bottle from a broken .pkg.
missing_roles() {  # missing_roles <asset-names>
  local names="$1" role pred missing="" opt_seen="" opt_missing="" excused=""
  for role in "${_ASSET_ROLES[@]}"; do
    retired_asset_role "$role" && continue
    if carries "$names" "$role"; then
      optional_asset_role "$role" && opt_seen=1
    elif optional_asset_role "$role"; then
      opt_missing="$opt_missing $role"
    else
      missing="$missing $role"
    fi
  done
  if [ -n "$opt_missing" ]; then
    if [ -z "$opt_seen" ]; then
      if [ -z "${_OPTIONAL_ASSET_PREDECESSORS[*]+set}" ]; then
        excused=1
      else
        for pred in "${_OPTIONAL_ASSET_PREDECESSORS[@]}"; do
          carries "$names" "$pred" && excused=1
        done
      fi
    fi
    [ -n "$excused" ] || missing="$missing$opt_missing"
  fi
  # Bottles are not a reconciled role (see asset-roles.sh), but a release is not installable
  # without them, so they are waited for here by name.
  printf '%s\n' "$names" | grep -q 'bottle\.tar\.gz$' || missing="$missing *.bottle.tar.gz"
  printf '%s' "$missing"
}

# A wall-clock deadline rather than a countdown of iterations. The GitHub check deliberately sleeps
# on its own cadence, so counting iterations would make the real budget depend on WHICH thing we are
# waiting for — a release whose local side went ready early would get a shorter deadline than one
# that did not, and the documented budget above would stop being the budget.
# Sourced by tests/test-wait-for-release.sh to exercise the role logic without a network.
[ -z "${WAIT_FOR_RELEASE_NO_POLL:-}" ] || return 0

DEADLINE=$(( $(date +%s) + ATTEMPTS * INTERVAL ))
missing=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  rel=$(fetch "$API" || true)
  names=$(printf '%s' "$rel" | jq -r '.assets[]?.name' 2>/dev/null || true)
  missing="$(missing_roles "$names")"
  if [ -z "$missing" ]; then
    if tap_ready "$rel" && registry_ready; then
      if github_ready; then
        echo "$TAG is complete, the tap advertises the bottles it is serving, and apt/dnf have it"
        exit 0
      fi
      # Its own cadence, not the loop's — see GH_INTERVAL.
      echo "  release complete here; waiting for the GitHub release to catch up to $TAG"
      sleep "$GH_INTERVAL"; continue
    fi
    echo "  release complete; waiting for the tap ($FORMULA) and the apt/dnf registry to catch up to $TAG"
  else
    echo "  waiting: $TAG does not carry$missing yet"
  fi
  sleep "$INTERVAL"
done
echo "::error::$TAG never became installable — nothing to install-test${missing:+ (still missing:$missing)}" >&2
exit 1
