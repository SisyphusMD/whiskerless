#!/usr/bin/env bash
# Push the built .deb/.rpm into Forgejo's native Debian and RPM registries, so a
# user gets `apt install whiskerless` and `dnf install whiskerless` instead of
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

[ "$#" -ge 4 ] || { echo "usage: $0 <host> <token> <tag> <package...>" >&2; exit 2; }
host="$1"; token="$2"; tag="$3"; shift 3

case "$tag" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "not a release tag: $tag" >&2; exit 2 ;;
esac

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

api="https://${host}/api/packages/SisyphusMD"
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
    "whiskerless_${version}_amd64.deb" \
    "whiskerless_${version}_arm64.deb" \
    "whiskerless-${version}.x86_64.rpm" \
    "whiskerless-${version}.aarch64.rpm"
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

upload() {  # upload <file> <url>
  local code
  code=$(curl --max-time 300 -sS -o "$body" -w '%{http_code}' -X PUT \
    -H "$auth" --upload-file "$1" "$2")
  case "$code" in
    201) echo "    $(basename "$1") → 201" ;;
    # This workflow is dispatchable so a partly-failed publish can be finished
    # without cutting a new release, which means every step has to survive being
    # run twice. Forgejo answers a re-upload with 409 "package file already
    # exists" — the desired end state, reached by the first run.
    409) echo "    $(basename "$1") → 409 already present" ;;
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
# rpm reports its version with the release suffix (`0.2.0~rc.28-1`) while debian
# reports it bare, so each is queried on its own terms rather than a shared
# guess.
verify() {  # verify <type> <registry-version> <expected-file>...
  local type="$1" rv="$2" listed missing=""
  shift 2
  listed=$(curl --max-time 60 --retry 2 --retry-connrefused --retry-max-time 120 -sSf -H "$auth" \
    "https://${host}/api/v1/packages/SisyphusMD/${type}/whiskerless/${rv}/files" | jq -r '.[].name') || {
      echo "::error::could not list $type files for whiskerless $rv"; return 1; }
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
  # shellcheck disable=SC2086
  verify rpm "$version-1" $rpms || failed="$failed rpm-verify"
fi

if [ -n "$failed" ]; then
  echo "::error::registry publishing failed for:$failed"
  exit 1
fi
echo "  registry publish complete for $tag ($dists)"
