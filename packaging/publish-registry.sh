#!/usr/bin/env bash
# Push the built .deb/.rpm into Forgejo's native Debian and RPM registries, so a
# user gets `apt install <project>` and `dnf install <project>` instead of
# downloading a file and running `dpkg -i` on it.
#   publish-registry.sh <host> <token> <tag> <package...>
#
# Only the PUBLIC Forgejo is worth publishing to: a repository is a URL every
# subscriber's package manager resolves on every update, and the NAS instance is
# not reachable from outside the house.
#
# Endpoints confirmed against the live instance (Forgejo 16.0.2), not from
# memory — the RPM registry takes a *group* where Debian takes a
# distribution+component, and neither shape is guessable from the other:
#   PUT /api/packages/{owner}/debian/pool/{distribution}/{component}/upload
#   PUT /api/packages/{owner}/rpm/{group}/upload
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# The project's identity, so this file is byte-identical in every repo that vendors it. A missing
# project.env is named rather than allowed to expand to an empty owner and publish into `/api/
# packages//debian/...`, which a forge would answer with a confusing 404.
[ -f "$here/project.env" ] || {
  echo "$0: packaging/project.env is missing — cannot resolve this project's registry" >&2
  exit 2
}
# shellcheck source=/dev/null
. "$here/project.env"
# For rel_validate_tag — one definition of what a release tag is, shared with every other step.
# shellcheck source=/dev/null
. "$here/release-common.sh"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
OWNER="${PROJECT_REPO_SLUG%%/*}"
PKG="${PROJECT_REPO_SLUG#*/}"

[ "$#" -ge 4 ] || { echo "usage: $0 <host> <token> <tag> <package...>" >&2; exit 2; }
host="$1"; token="$2"; tag="$3"; shift 3

# The SAME grammar the release helpers enforce, not a looser glob of its own. `v1.2.3.dev1` and
# `v1.2.3-anything` passed the glob, were classified stable for having no hyphen in the right
# place, and would have been published into the `stable` distribution that real installs track —
# while every other step in the release path rejected the same tag.
rel_validate_tag "$tag" || exit 2

# A release candidate must never reach a subscriber who asked for releases, and
# deb/rpm version ordering cannot express that on its own: `0.2.0~rc.28` sorts
# below `0.2.0`, which only helps once 0.2.0 exists. Until then the newest thing
# in the repository IS the candidate, and everyone upgrades onto it. So the two
# audiences are separated by distribution instead.
#
# A stable release publishes to BOTH. Whoever subscribed to `testing` was
# following this version's candidates; leaving the release out of their
# distribution would strand them on the last rc forever, and prune-rcs deleting
# that rc would then take the package away from them entirely.
case "$tag" in
  *-*) dists="testing" ;;
  *)   dists="stable testing" ;;
esac

api="https://${host}/api/packages/${OWNER}"
auth="Authorization: token ${token}"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT

# The tag spelling is not the package spelling: nfpm builds `0.2.0~rc.28`
# because deb and rpm both need the tilde to sort a candidate below its release.
version="${tag#v}"
version="${version/-rc./~rc.}"

# A repository is not a release page: whatever lands here is what `apt install`
# and `dnf install` hand people, immediately, with no way to tell that the set is
# short. So the COMPLETE set is required before anything is uploaded — every
# architecture, both formats — rather than trusting the caller to pass it.
#
# The workflow builds amd64 fully before it starts arm64 and smoke-tests neither
# until both are done, so "some of the packages exist" is a real state on disk
# after a failed build, not a hypothetical.
expected_files() {
  printf '%s\n' \
    "${PKG}_${version}_amd64.deb" \
    "${PKG}_${version}_arm64.deb" \
    "${PKG}-${version}.x86_64.rpm" \
    "${PKG}-${version}.aarch64.rpm"
}
given=""
for pkg in "$@"; do given="$given $(basename "$pkg")"; done
short=""
while read -r want; do
  case " $given " in
    *" $want "*) ;;
    *) short="$short $want" ;;
  esac
done < <(expected_files)
if [ -n "$short" ]; then
  echo "::error::refusing to publish a partial package set for $tag — missing:$short" >&2
  echo "  given:$given" >&2
  exit 1
fi

# remote_matches <file> <download-url> — whether the already-published object is byte-identical.
#
# The DOWNLOAD url, never the upload one. `.../upload` is a PUT endpoint and answers GET with 405,
# so comparing against it failed for every existing file and reported each idempotent re-run as a
# differing artifact — which made finishing a partially-failed publish impossible, the one job the
# 409 branch exists to do. Both download paths below were confirmed against the live instance:
#
#   deb  GET {api}/debian/pool/{distribution}/{component}/{filename}
#   rpm  GET {api}/rpm/{group}/package/{name}/{version}/{arch}
#
# rpm is not the name it was uploaded under: the registry renames on ingest and appends the release
# suffix, so the stored version is `<version>-1` and the arch is a path segment rather than part of
# a filename.
# A 409 is idempotent only if it is; otherwise the name has been reused for different content, and
# an unreadable object is not evidence either way, so that counts as a mismatch too.
remote_matches() {
  local stored rc
  stored=$(mktemp)
  # A read, so a repeat costs nothing but time; retried for the same reset-mid-transfer reason.
  local dl=1
  while ! curl --max-time 300 -sSfL -H "$auth" -o "$stored" "$2"; do
    [ "$dl" -ge 3 ] && break
    rm -f "$stored"; sleep $((dl * 3)); dl=$((dl + 1))
  done
  if [ -s "$stored" ]; then
    cmp -s "$1" "$stored"
    rc=$?
  else
    rc=1
  fi
  rm -f "$stored"
  return "$rc"
}

# download_url <file> <upload-url> — where the registry will SERVE what this upload stores.
download_url() {
  local file="$1" up="$2" name version arch
  name="$(basename "$file")"
  case "$name" in
    *.deb) printf '%s/%s' "${up%/upload}" "$name" ;;
    *.rpm)
      # `<pkg>-<version>.<arch>.rpm` -> group, name, version-1, arch.
      arch="${name%.rpm}"; arch="${arch##*.}"
      version="${name%.*.rpm}"; version="${version#"${PKG}-"}"
      printf '%s/rpm/%s/package/%s/%s-1/%s' "$api" "$dist" "$PKG" "$version" "$arch" ;;
    *) printf '%s' "$up" ;;
  esac
}

upload() {  # upload <file> <upload-url>
  local code attempt=1
  # Retried HERE rather than with curl's --retry, for the reason release-common.sh gives: the
  # failure that actually happens is a reset mid-transfer, which --retry does not classify as
  # transient, and --retry-all-errors would retry a write blindly. This layer can do what curl
  # cannot — a repeat lands on 409 below, which refuses to report success until it has verified the
  # stored bytes are these bytes. So the retry is safe precisely because the check follows it.
  while :; do
    code=$(curl --max-time 300 -sS -o "$body" -w '%{http_code}' -X PUT \
      -H "$auth" --upload-file "$1" "$2") && break
    if [ "$attempt" -ge 4 ]; then
      # The transfer may have STORED the bytes and lost the response on the way back, which is what
      # a reset mid-upload looks like from here. Failing now would redden a release that actually
      # published. Ask the registry what it holds before giving up — the same question the 409 path
      # asks, and the only one that can tell those two outcomes apart.
      if remote_matches "$1" "$(download_url "$1" "$2")"; then
        echo "    $(basename "$1") → stored despite a lost response (bytes verified)"; return 0
      fi
      echo "::error::PUT $2 failed to complete after $attempt attempts" >&2; return 1
    fi
    echo "    $(basename "$1") → transfer failed, retrying ($attempt)"
    sleep $((attempt * 5)); attempt=$((attempt + 1))
  done
  case "$code" in
    201) echo "    $(basename "$1") → 201" ;;
    # This workflow is dispatchable so a partly-failed publish can be finished
    # without cutting a new release, which means every step has to survive being
    # run twice. Forgejo answers a re-upload with 409 "package file already
    # exists" — which is the desired end state ONLY IF the stored bytes are the
    # ones being uploaded. 409 says a file with this name exists, not that the
    # same file exists, so a re-drive after a rebuild would otherwise report
    # success while the registry kept serving the superseded package. Confirm it.
    409)
      if remote_matches "$1" "$(download_url "$1" "$2")"; then
        echo "    $(basename "$1") → 409 already present (bytes verified)"
      else
        echo "::error::$2 already holds DIFFERENT bytes; publish these under a new version" >&2
        return 1
      fi
      ;;
    *)   echo "::error::PUT $2 returned $code: $(cat "$body")"; return 1 ;;
  esac
}

failed=""
for dist in $dists; do
  echo "  distribution: $dist"
  for pkg in "$@"; do
    case "$pkg" in
      *.deb) upload "$pkg" "$api/debian/pool/$dist/main/upload" || failed="$failed $pkg@$dist" ;;
      *.rpm) upload "$pkg" "$api/rpm/$dist/upload"              || failed="$failed $pkg@$dist" ;;
      *) echo "    skipping $(basename "$pkg") — not a .deb or .rpm" ;;
    esac
  done
done

# A 201 says the file was accepted, not that it reached the index a package
# manager reads. Ask the registry what it now holds and require every file back,
# because the failure this guards against — a release that looks published and
# serves nothing — is invisible until a user runs `apt install`.
#
# Each format is asked on its own terms, because they differ twice over:
#
#   version   rpm reports the release suffix (`0.2.0~rc.28-1`), debian is bare.
#   filename  rpm is RENAMED on ingest to its canonical
#             `<name>-<version>-<release>.<arch>.rpm`, so what was uploaded as
#             `<pkg>-0.2.0~rc.28.x86_64.rpm` is stored as
#             `<pkg>-0.2.0~rc.28-1.x86_64.rpm`. debian keeps the name it was
#             given, so comparing the local basename passes there and fails here.
#
# The `-1` comes from the same place as the version suffix above, so if nfpm's
# release ever moves, both move together.
verify() {  # verify <type> <registry-version> <expected-file>...
  local type="$1" rv="$2" listed missing=""
  shift 2
  listed=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf -H "$auth" \
    "https://${host}/api/v1/packages/${OWNER}/${type}/${PKG}/${rv}/files" | jq -r '.[].name') || {
      echo "::error::could not list $type files for $PKG $rv"; return 1; }
  for want in "$@"; do
    printf '%s\n' "$listed" | grep -Fqx "$want" || missing="$missing $want"
  done
  if [ -n "$missing" ]; then
    echo "::error::$type registry is missing:$missing"
    echo "  it holds: $(printf '%s' "$listed" | tr '\n' ' ')"
    return 1
  fi
  echo "  $type $rv holds $(printf '%s\n' "$listed" | grep -c .) file(s)"
}

debs=""; rpms=""
for pkg in "$@"; do
  case "$pkg" in
    *.deb) debs="$debs $(basename "$pkg")" ;;
    *.rpm) rpms="$rpms $(basename "$pkg")" ;;
  esac
done
if [ -n "$debs" ]; then
  # shellcheck disable=SC2086 # deliberate word-splitting: each name is one argument
  verify debian "$version" $debs || failed="$failed debian-verify"
fi
if [ -n "$rpms" ]; then
  # <pkg>-0.2.0~rc.28.x86_64.rpm -> <pkg>-0.2.0~rc.28-1.x86_64.rpm
  stored_rpms=$(printf '%s' "$rpms" | tr ' ' '\n' | sed -E '/^$/d; s/\.([^.]+)\.rpm$/-1.\1.rpm/' | tr '\n' ' ')
  # shellcheck disable=SC2086
  verify rpm "$version-1" $stored_rpms || failed="$failed rpm-verify"
fi

if [ -n "$failed" ]; then
  echo "::error::registry publishing failed for:$failed"
  exit 1
fi
echo "  registry publish complete for $tag ($dists)"
