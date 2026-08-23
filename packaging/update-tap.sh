#!/usr/bin/env bash
# Fill the Homebrew formulas for a release from a LOCAL build of the sdist, then require PyPI to be
# serving exactly those bytes. A registry download is what the formula checksum is supposed to
# protect users from, so it is never the source of that checksum.
#   update-tap.sh <tag> <tap-clone-dir> [bottle-manifest-dir]
#
# Run TWICE per release. The first pass (no manifest dir) publishes the formula as soon as PyPI has
# the sdist, because the bottles are built by installing that formula and cannot exist before it.
# The second pass, once they do, re-renders the same version with a `bottle do` block so nobody
# compiles cryptography again. A release is usable after either pass; only the second is fast.
#
# Verified reproducible for this project: building the sdist from the v0.1.3 tag reproduces the
# sha256 PyPI serves for 0.1.3, byte for byte. If that ever stops being true this script fails loudly
# rather than publishing a formula whose checksum came from the thing it is meant to guard.
#
# A prerelease tag (hyphenated, e.g. v0.2.0-rc.1) writes ONLY the separate `<name>-rc` formula,
# so the stable formula never points at a candidate. A stable tag writes BOTH: the stable formula,
# and the rc formula re-pointed at the same stable release, so `brew install <name>-rc` keeps
# resolving once that version's candidates are pruned.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || { echo "usage: $0 <tag> <tap-clone-dir> [bottle-manifest-dir]" >&2; exit 2; }
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
PKG="${PROJECT_REPO_SLUG#*/}"
# shellcheck source=/dev/null
. "$here/release-common.sh"

tag="$1"; tapdir="$2"; manifests="${3:-}"
[ -z "$manifests" ] || [ -d "$manifests" ] || { echo "not a directory: $manifests" >&2; exit 2; }
# The SAME grammar every other release step enforces, from release-common.sh.
rel_validate_tag "$tag"
version="${tag#v}"
# PEP 440: the tag says 0.2.0-rc.1, PyPI normalizes the file to 0.2.0rc1.
pypi_version="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
# PEP 625: the sdist FILENAME normalises `-` to `_`, while the directory segment keeps the project
# name as published. `dreame-valetudo-0.2.1.tar.gz` 404s; `dreame_valetudo-0.2.1.tar.gz` is served.
# Verified against both consumers' real URLs. A project whose name has no hyphen never sees the
# difference, which is how this stayed hidden until one did.
sdist_name="$(printf '%s' "$PKG" | tr '-' '_')-${pypi_version}.tar.gz"
url="https://files.pythonhosted.org/packages/source/${PKG:0:1}/${PKG}/${sdist_name}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Built from a pristine export of the tag, never from the working tree. hatchling sweeps untracked,
# un-ignored files into the sdist, so anything sitting beside the checkout — a tap clone, a build
# directory — silently changes the hash and fails the comparison below for a reason that has nothing
# to do with PyPI. Exporting also means what gets verified is the tag itself, which is what shipped.
mkdir -p "$work/src"
if git -C "$root" rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null 2>&1; then
  src_ref="refs/tags/$tag"
else
  # A shallow checkout of a tag push does not always carry the tag ref; HEAD is that commit.
  src_ref="HEAD"
fi
git -C "$root" archive --format=tar "$src_ref" | tar -x -C "$work/src"
# hatchling is reproducible here, so this is the same artifact publish.yml uploaded — and if it is
# not, the comparison below says so.
python3 -m build --sdist --outdir "$work/local" "$work/src" >/dev/null
local_sdist="$work/local/$sdist_name"
[ -f "$local_sdist" ] || { echo "local build did not produce $local_sdist" >&2; ls "$work/local" >&2; exit 1; }

if command -v sha256sum >/dev/null 2>&1; then shacmd="sha256sum"; else shacmd="shasum -a 256"; fi
sha="$($shacmd "$local_sdist" | awk '{print $1}')"
[ -n "$sha" ] || { echo "could not hash $local_sdist" >&2; exit 1; }

# PyPI must already serve exactly these bytes. Homebrew would otherwise surface a mismatch as an
# install-time checksum failure for whoever happened to install first.
# -f so an HTTP error page is never hashed as if it were the sdist.
#
# Polled rather than fetched once: this runs seconds after the upload job, and
# files.pythonhosted.org serves a 404 for a little while after twine reports
# success. curl's --retry does not treat 404 as retryable, so a fresh release
# raced the CDN and failed a check that had nothing wrong with it.
downloaded=""
# Overridable so a test can assert the give-up path without paying the real CDN grace period. The
# default is the only value a release ever uses; the prune sweep exposes PRUNE_RETRY_SLEEP for the
# same reason.
window="${TAP_DOWNLOAD_WINDOW:-300}"
deadline=$(( $(date +%s) + window ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  # No --retry here: the outer loop IS the retry, and nesting one inside the other let a stalling
  # CDN run four 120s attempts per iteration and blow the five minutes this claims to bound.
  if curl -fsSL --connect-timeout 10 --max-time 60 "$url" -o "$work/remote.tar.gz"; then
    downloaded=1
    break
  fi
  sleep 10
done
[ -n "$downloaded" ] || { echo "could not download the published sdist within ${window}s: $url" >&2; exit 1; }
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
#
# The bottle pass re-renders the version that is ALREADY there, so it accepts an
# equal version — refusing it would leave every release un-bottled, which is the
# silent slow-compile this whole mechanism exists to prevent.
newer_than_tap() {
  local formula="$1" out="$tapdir/Formula/$1.rb" existing allow_equal=false
  [ -z "$manifests" ] || allow_equal=true
  [ -f "$out" ] || return 0                       # nothing published yet
  existing="$(sed -n "s|.*/$(printf '%s' "$PKG" | tr '-' '_')-\(.*\)\.tar\.gz\".*|\1|p" "$out" | head -1)"
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
allow_equal = sys.argv[3] == "true"
if existing is None:          # hand-edited or unrecognised: let the release win
    sys.exit(0)
if incoming is None:
    sys.exit(1)
sys.exit(0 if (incoming >= existing if allow_equal else incoming > existing) else 1)
' "$existing" "$pypi_version" "$allow_equal"
}

# Bottles are served from this release's assets, so the URL carries the TAG
# spelling (v0.2.0-rc.28), not PyPI's normalized one. A stable tag re-points the
# rc formula at its own release, which is why that release has to carry a full
# set of `<name>-rc-` bottles as well as `<name>-`.
root_url="https://forgejo.bryantserver.com/${PROJECT_REPO_SLUG}/releases/download/${tag}"

render_formula() {
  local formula="$1" out block
  if ! newer_than_tap "$formula"; then
    echo "tap already holds $formula at a version >= $pypi_version; refusing to move it back"
    return 0
  fi
  mkdir -p "$tapdir/Formula"
  out="$tapdir/Formula/${formula}.rb"
  # Always a file, and never empty: `sed r` on an empty file would swallow the
  # blank line the marker stands in for and glue the block to `license`.
  if [ -n "$manifests" ]; then
    # --expect-tags 4 is the whole point of a separate pass: a platform whose
    # bottle never arrived is otherwise invisible, and its users quietly go back
    # to compiling cryptography for several minutes.
    block="$work/${formula}.block"
    python3 "$here/bottle-block.py" --formula "$formula" --version "$pypi_version" \
      --root-url "$root_url" --expect-tags 4 "$manifests"/*.json > "$block"
    bash "$here/render-formula.sh" "$here/homebrew/${formula}.rb" "$pypi_version" "$sha" "$block" > "$out"
  else
    bash "$here/render-formula.sh" "$here/homebrew/${formula}.rb" "$pypi_version" "$sha" > "$out"
  fi
  # Spelled as an explicit `if` rather than `A && B || C`: that reads as if-then-else
  # and is not (shellcheck SC2015), which is a bad shape for the check standing
  # between a template and a published formula.
  if ! grep -Fq "url \"$url\"" "$out" || ! grep -Fq "sha256 \"$sha\"" "$out"; then
    echo "formula template substitution failed for $formula" >&2
    exit 1
  fi
  # A bottle pass that rendered no block would publish, report success, and leave
  # every user compiling — the exact failure it was added to remove.
  if [ -n "$manifests" ] && ! grep -Fq "bottle do" "$out"; then
    echo "bottle pass produced no bottle block for $formula" >&2
    exit 1
  fi
  echo "wrote $out (tag=$tag sha=$sha${manifests:+ +bottles})"
}

case "$tag" in
  *-*) render_formula "$PKG-rc" ;;               # prerelease: only the rc channel moves
  *)   render_formula "$PKG"
       render_formula "$PKG-rc" ;;               # fall-through: rc re-points at the stable release
esac
