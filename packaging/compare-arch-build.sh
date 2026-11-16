#!/usr/bin/env bash
# Compare this runner's build of one architecture's release assets with the copies already on the
# release, which another runner built and appended.
#
#   compare-arch-build.sh <tag> <asset>...
#
# For moving a release build to a new runner: both build the same tag, and this says whether the
# new one produced the same thing. The bytes always differ (timestamps, frozen bundles), so it
# compares what a user's package manager sees instead: the asset names, the package metadata and
# file lists, the signatures, and the archive contents. Our build's own smoke tests already ran.
#
# Waits for the other copies, because the two builds finish independently. Prints one line per
# check and a final `VERDICT agree|differ|unknown`. Exit 0 agree, 1 differ, 2 unknown.
# The inspections below are called by name, through check().
# shellcheck disable=SC2329
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

tag="${1:?usage: compare-arch-build.sh <tag> <asset>...}"
shift
[ "$#" -gt 0 ] || { echo "no assets to compare" >&2; exit 2; }
: "${FORGE:?FORGE must be set}" "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
timeout="${ARCH_COMPARE_TIMEOUT:-5400}"
theirs="$(mktemp -d)"
gpghome="$(mktemp -d)"
trap 'rm -rf "$theirs" "$gpghome"' EXIT

api="$FORGE/api/v1/repos/$GITHUB_REPOSITORY/releases/tags/$tag"
deadline=$(( $(date +%s) + timeout ))
echo "waiting up to $(( timeout / 60 )) min for the other runner's copies on $tag"
while :; do
  release="$(curl -fsS --max-time 30 "$api" 2>/dev/null || true)"
  missing=""
  [ -n "$release" ] || missing=" (the release itself)"
  for asset in "$@"; do
    name="$(basename "$asset")"
    printf '%s' "$release" | jq -e --arg n "$name" 'any(.assets[]?; .name == $n)' >/dev/null 2>&1 \
      || missing="$missing $name"
  done
  [ -z "$missing" ] && break
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "VERDICT unknown: still missing from the release:$missing"
    exit 2
  fi
  sleep 60
done

for asset in "$@"; do
  name="$(basename "$asset")"
  url="$(printf '%s' "$release" | jq -r --arg n "$name" 'first(.assets[] | select(.name == $n) | .browser_download_url)')"
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 --max-time 600 -o "$theirs/$name" "$url" \
    || { echo "VERDICT unknown: could not download the other copy of $name"; exit 2; }
done

GNUPGHOME="$gpghome" gpg --batch --quiet --import "$here/sisyphusmd-signing-key.asc" 2>/dev/null \
  || { echo "VERDICT unknown: could not import the signing key"; exit 2; }
differ=0
unreadable=0
# check <what> <inspect-function>: run the inspection on both copies and compare what it prints.
# An inspection that fails on either copy is "could not tell", never "same": two empty outputs
# would otherwise compare equal.
check() {
  local what="$1" fn="$2" ours theirs_out
  if ! ours="$("$fn" "$mine")" || ! theirs_out="$("$fn" "$other")"; then
    echo "UNREADABLE $what"
    unreadable=1
    return 0
  fi
  if [ "$ours" = "$theirs_out" ]; then
    # A one-line answer is shown, so "same" can be read as "both signed", not "both unsigned".
    case "$ours" in
      *$'\n'*) echo "SAME   $what" ;;
      *) echo "SAME   $what: $ours" ;;
    esac
  else
    echo "DIFF   $what"
    diff <(printf '%s\n' "$theirs_out") <(printf '%s\n' "$ours") | sed 's/^/         /' || true
    differ=1
  fi
}

# `tar -tv` minus the size and date: type, mode, owner, path, and a link's target are what an
# install lays down; sizes and times differ between any two builds.
tar_listing() { tar -tv "$@" | awk '{ mode = $1; owner = $2; for (i = 1; i <= 5; i++) sub(/^[^ ]+ +/, ""); print mode, owner, $0 }' | sort; }
deb_control() { dpkg-deb -f "$1" | { grep -v '^Installed-Size:' || true; }; }
deb_files() { dpkg-deb --fsys-tarfile "$1" | tar_listing; }
deb_members() { ar t "$1"; }
# A .deb signed by nfpm carries a detached signature, `_gpgorigin`, over the concatenated members.
deb_signature() {
  local work deb
  deb="$(realpath "$1")"
  work="$(mktemp -d)"
  ( cd "$work" && ar x "$deb" ) || { rm -rf "$work"; return 1; }
  if [ ! -f "$work/_gpgorigin" ]; then
    echo "unsigned"
  elif cat "$work/debian-binary" "$work"/control.tar.* "$work"/data.tar.* \
       | GNUPGHOME="$gpghome" gpg --batch --verify "$work/_gpgorigin" - >/dev/null 2>&1; then
    echo "good signature"
  else
    echo "BAD signature"
  fi
  rm -rf "$work"
}
rpm_header() { rpm -qp --nosignature --qf '%{NAME} %{VERSION} %{RELEASE} %{ARCH} %{LICENSE}\n' "$1"; }
rpm_requires() { rpm -qp --nosignature --requires "$1" | sort; }
rpm_provides() { rpm -qp --nosignature --provides "$1" | sort; }
rpm_files() {
  rpm -qp --nosignature --qf '[%{FILEMODES:perms} %{FILEUSERNAME}/%{FILEGROUPNAME} %{FILENAMES} -> %{FILELINKTOS}\n]' "$1" \
    | sed 's/ -> $//' | sort
}
# `rpm -K` exits non-zero for a bad or missing signature; that is an answer to compare, not a
# failed inspection, so only an empty answer counts as one.
rpm_signature() {
  local out
  out="$(rpm --dbpath "$rpmdb" -K "$1" 2>&1 | sed 's/^[^:]*: //')"
  [ -n "$out" ] && printf '%s\n' "$out"
}
tar_contents() { tar_listing -zf "$1"; }
sums_names() { awk '{print $2}' "$1" | sort; }
file_type() { file -b "$1" | sed -E 's/BuildID\[[^]]*\]=[0-9a-f]+, //'; }

rpmdb="$(mktemp -d)"
trap 'rm -rf "$theirs" "$gpghome" "$rpmdb"' EXIT
rpm --dbpath "$rpmdb" --import "$here/sisyphusmd-signing-key.asc" 2>/dev/null \
  || { echo "VERDICT unknown: could not import the signing key for rpm"; exit 2; }

for asset in "$@"; do
  name="$(basename "$asset")"
  mine="$asset"; other="$theirs/$name"
  case "$name" in
    *.deb)
      check "$name control" deb_control
      check "$name files" deb_files
      check "$name members" deb_members
      check "$name signature" deb_signature
      ;;
    *.rpm)
      check "$name header" rpm_header
      check "$name requires" rpm_requires
      check "$name provides" rpm_provides
      check "$name files" rpm_files
      check "$name signature" rpm_signature
      ;;
    *.tar.gz)
      check "$name contents" tar_contents
      ;;
    SHA256SUMS-*)
      check "$name names" sums_names
      ;;
    *)
      check "$name type" file_type
      ;;
  esac
done

if [ "$differ" -ne 0 ]; then
  echo "VERDICT differ"
  exit 1
fi
if [ "$unreadable" -ne 0 ]; then
  echo "VERDICT unknown: an inspection failed on one of the copies"
  exit 2
fi
echo "VERDICT agree"
exit 0
