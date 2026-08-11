#!/usr/bin/env bash
# Fill the Homebrew formulas for a release from a LOCAL build of the sdist, then require PyPI to be
# serving exactly those bytes. A registry download is what the formula checksum is supposed to
# protect users from, so it is never the source of that checksum.
#   update-tap.sh <tag> <tap-clone-dir>
#
# Verified reproducible for this project: building the sdist from the v0.1.3 tag reproduces the
# sha256 PyPI serves for 0.1.3, byte for byte. If that ever stops being true this script fails loudly
# rather than publishing a formula whose checksum came from the thing it is meant to guard.
#
# A prerelease tag (hyphenated, e.g. v0.2.0-rc.1) writes ONLY the separate `whiskerless-rc` formula,
# so the stable formula never points at a candidate. A stable tag writes BOTH: the stable formula,
# and the rc formula re-pointed at the same stable release, so `brew install whiskerless-rc` keeps
# resolving once that version's candidates are pruned.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"

[ "$#" -eq 2 ] || { echo "usage: $0 <tag> <tap-clone-dir>" >&2; exit 2; }
tag="$1"; tapdir="$2"
case "$tag" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "not a release tag: $tag" >&2; exit 2 ;;
esac
version="${tag#v}"
# PEP 440: the tag says 0.2.0-rc.1, PyPI normalizes the file to 0.2.0rc1.
pypi_version="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
url="https://files.pythonhosted.org/packages/source/w/whiskerless/whiskerless-${pypi_version}.tar.gz"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Built from the checked-out tag, not downloaded. hatchling is reproducible here, so this is the
# same artifact publish.yml uploaded — and if it is not, the comparison below says so.
python3 -m build --sdist --outdir "$work/local" "$root" >/dev/null
local_sdist="$work/local/whiskerless-${pypi_version}.tar.gz"
[ -f "$local_sdist" ] || { echo "local build did not produce $local_sdist" >&2; ls "$work/local" >&2; exit 1; }

if command -v sha256sum >/dev/null 2>&1; then shacmd="sha256sum"; else shacmd="shasum -a 256"; fi
sha="$($shacmd "$local_sdist" | awk '{print $1}')"
[ -n "$sha" ] || { echo "could not hash $local_sdist" >&2; exit 1; }

# PyPI must already serve exactly these bytes. Homebrew would otherwise surface a mismatch as an
# install-time checksum failure for whoever happened to install first.
# -f so an HTTP error page is never hashed as if it were the sdist.
curl -fsSL --retry 5 --retry-delay 3 --connect-timeout 10 --max-time 120 "$url" -o "$work/remote.tar.gz" \
  || { echo "could not download the published sdist: $url" >&2; exit 1; }
remote_sha="$($shacmd "$work/remote.tar.gz" | awk '{print $1}')"
[ "$remote_sha" = "$sha" ] || {
  echo "PyPI sdist does not match the locally built one" >&2
  echo "  local : $sha" >&2
  echo "  pypi  : $remote_sha" >&2
  exit 1
}

# Publishing is not serialized: two tag builds can overlap, and an old run can be
# re-run long after a newer release. Whoever clones last would otherwise win and
# repoint the channel BACKWARDS, silently downgrading everyone on `brew upgrade`.
# Compare against whatever the tap already holds and refuse to go back.
newer_than_tap() {
  local formula="$1" out="$tapdir/Formula/$1.rb" existing
  [ -f "$out" ] || return 0                       # nothing published yet
  existing="$(sed -n 's|.*/whiskerless-\(.*\)\.tar\.gz".*|\1|p' "$out" | head -1)"
  [ -n "$existing" ] || return 0                  # unparseable; treat as first write
  # Ordering is PEP 440, not `sort -V`: sort -V ranks 0.2.0rc1 AFTER 0.2.0, which
  # would refuse the stable fall-through that re-points the rc channel at its own
  # release. Stdlib only — depending on `packaging` here fails CLOSED if it is
  # missing, silently blocking every tap update.
  python3 -c '
import re, sys

def key(value):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?", value)
    if not m:
        return None
    major, minor, patch, rc = m.groups()
    # tier 0 = release candidate, 1 = the release itself, so rc sorts first.
    return (int(major), int(minor), int(patch), 0 if rc else 1, int(rc or 0))

existing, incoming = key(sys.argv[1]), key(sys.argv[2])
if existing is None:          # hand-edited or unrecognised: let the release win
    sys.exit(0)
sys.exit(0 if incoming is not None and incoming > existing else 1)
' "$existing" "$pypi_version"
}

render_formula() {
  local formula="$1" out
  if ! newer_than_tap "$formula"; then
    echo "tap already holds $formula at a version >= $pypi_version; refusing to move it back"
    return 0
  fi
  mkdir -p "$tapdir/Formula"
  out="$tapdir/Formula/${formula}.rb"
  sed -e "s|REPLACE_PYPI_VERSION|${pypi_version}|g" \
      -e "s|REPLACE_VERSION|${pypi_version}|g" \
      -e "s|REPLACE_SDIST_SHA256|${sha}|" \
      "$here/homebrew/${formula}.rb" > "$out"
  grep -Fq "url \"$url\"" "$out" \
    && grep -Fq "sha256 \"$sha\"" "$out" \
    && ! grep -Eq 'REPLACE_(PYPI_)?VERSION|REPLACE_SDIST_SHA256' "$out" \
    || { echo "formula template substitution failed for $formula" >&2; exit 1; }
  echo "wrote $out (tag=$tag sha=$sha)"
}

case "$tag" in
  *-*) render_formula whiskerless-rc ;;          # prerelease: only the rc channel moves
  *)   render_formula whiskerless
       render_formula whiskerless-rc ;;          # fall-through: rc re-points at the stable release
esac
