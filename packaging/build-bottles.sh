#!/usr/bin/env bash
# Build this platform's Homebrew bottles for a release, and leave them in <outdir>
# under the names Homebrew will later ask for.
#   build-bottles.sh <tag> <outdir>
#
# A bottle is produced by INSTALLING the published formula from source, so this
# can only run after publish.yml's first tap pass — it waits for that rather than
# assuming it, because bottling last release's formula would silently publish a
# block whose files this release never uploaded.
#
# Which formulae get bottled follows the same rule as the tap itself:
#
#   rc tag     → <project>-rc only
#   stable tag → <project> AND <project>-rc
#
# The second half of that is not redundancy. A stable tag re-points the rc
# formula at its own release, and a bottle's filename embeds the FORMULA name
# while the keg inside it is rooted at `<formula>/<version>/` — so a
# `<project>` bottle can be neither renamed nor relabelled into a
# `<project>-rc` one. Without its own set, `brew install <project>-rc` after a
# stable release finds no bottle it can use and quietly builds from source,
# which is the exact cost bottles were added to remove.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
[ -f "$here/project.env" ] || {
  echo "$0: packaging/project.env is missing — cannot resolve this project's tap or formulae" >&2
  exit 2
}
# shellcheck source=/dev/null
. "$here/project.env"
: "${PROJECT_REPO_SLUG:?project.env must define PROJECT_REPO_SLUG}"
OWNER="${PROJECT_REPO_SLUG%%/*}"
PKG="${PROJECT_REPO_SLUG#*/}"
# Homebrew tap names are lower-case; the forge owner is not necessarily.
TAP="$(printf '%s' "$OWNER" | tr '[:upper:]' '[:lower:]')/tap"

[ "$#" -eq 2 ] || { echo "usage: $0 <tag> <outdir>" >&2; exit 2; }
tag="$1"; outdir="$2"

case "$tag" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "not a release tag: $tag" >&2; exit 2 ;;
esac

version="${tag#v}"
# PEP 440, the same normalization update-tap.sh applies: the tag says 0.2.0-rc.1
# and the formula's URL says 0.2.0rc1. The bottle filename follows the formula.
pypi_version="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
# WHERE the formula installs from, which is what decides the version spelling in its url — and
# so the spelling this readiness check has to search for.
#
# `pypi`: the project publishes to PyPI and the formula builds from the sdist, whose filename PyPI
# normalises to PEP 440 (`0.2.0rc1`). Not a choice; PyPI names that file.
# `release-asset`: the project does not publish to PyPI, and the formula builds from an asset this
# release named for its tag (`0.3.0-rc.1`).
#
# Hardcoding either spelling made every prerelease bottle build in the OTHER project wait the full
# thirty minutes and then fail against a tap that had published correctly. The two only differ for
# release candidates — a stable `0.3.0` is spelled the same either way.
case "${PROJECT_FORMULA_SOURCE:-release-asset}" in
  pypi)          tarball_version="$pypi_version" ;;
  release-asset) tarball_version="$version" ;;
  *) echo "project.env: PROJECT_FORMULA_SOURCE must be 'pypi' or 'release-asset'" >&2; exit 2 ;;
esac
root_url="https://forgejo.bryantserver.com/${OWNER}/${PKG}/releases/download/${tag}"

case "$tag" in
  *-*) formulae="${PKG}-rc" ;;
  *)   formulae="${PKG} ${PKG}-rc" ;;
esac

mkdir -p "$outdir"
outdir="$(cd "$outdir" && pwd)"

export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_ENV_HINTS=1
# One deliberate update, up front, and no surprise ones later — which is what
# NO_AUTO_UPDATE is actually for. Skipping it entirely is not an option on the
# pinned linuxbrew image: its baked-in homebrew-core metadata and cached bottle
# manifests go stale against what ghcr.io serves, and installing a DEPENDENCY
# then dies in `Utils::Bottles.load_tab` with `undefined method '[]' for nil`.
# Reproduced in that image both ways. homebrew-smoke.Dockerfile has always done
# this; the bottle build had not, and that is the whole of why its Linux legs
# failed while the self-updating macOS runners passed.
brew update --quiet
# `brew tap-new`/`brew bottle` are developer commands and shell out to git for a
# commit; a runner has no identity configured and the command dies on it.
git config --global user.email "forgejo-actions[bot]@users.noreply.bryantserver.com"
git config --global user.name "forgejo-actions[bot]"

# Tapped from Forgejo, the primary. The GitHub copy is a push mirror and can lag
# a tap update by a poll interval — long enough to bottle the previous version.
if ! brew tap | grep -qx "$TAP"; then
  brew tap "$TAP" "https://forgejo.bryantserver.com/${OWNER}/homebrew-tap.git"
fi
tapdir="$(brew --repo "$TAP")"

# The formula this bottles has to be the one this release just published.
# Anything else produces bottles named for a version whose release will never
# carry them.
for _ in $(seq 1 90); do
  # `pull --ff-only`, not `reset --hard origin/HEAD`: a Homebrew tap clone does not
  # reliably carry the origin/HEAD symbolic ref, and resolving it is the kind of
  # thing that works here and dies on a runner. Failures are swallowed because
  # this loop is a WAIT — the assertion after it is what has to be strict, and a
  # transient fetch error should cost one iteration, not the release.
  git -C "$tapdir" pull --quiet --ff-only >/dev/null 2>&1 || true
  ready=true
  for formula in $formulae; do
    grep -Fq "${PKG}-${tarball_version}.tar.gz" "$tapdir/Formula/${formula}.rb" 2>/dev/null || ready=false
  done
  [ "$ready" = true ] && break
  sleep 20
done
for formula in $formulae; do
  grep -Fq "${PKG}-${tarball_version}.tar.gz" "$tapdir/Formula/${formula}.rb" 2>/dev/null || {
    echo "::error::the tap never published ${formula} at ${tarball_version} — nothing to bottle" >&2
    exit 1
  }
done

for formula in $formulae; do
  echo "=== bottling $formula $pypi_version ==="
  # The two formulae install the same binary and declare
  # conflicts_with each other, so they cannot be installed at once — hence one
  # at a time, with a clean uninstall between.
  brew uninstall --force "$PKG" "${PKG}-rc" >/dev/null 2>&1 || true
  brew install --build-bottle "$TAP/${formula}"
  ( cd "$outdir" && brew bottle --json --no-rebuild --root-url="$root_url" "$TAP/${formula}" )
  brew uninstall --force "$formula"
done

# `brew bottle` writes `<formula>--<version>.<tag>.bottle.tar.gz`, with a double
# dash that exists only so the local file cannot be mistaken for a published
# one. What Homebrew fetches is the single-dash `filename` recorded in the JSON,
# so rename to that — the release asset must be named what the block asks for.
cd "$outdir"
for f in ./*--*.bottle.tar.gz; do
  [ -e "$f" ] || continue
  mv "$f" "$(printf '%s' "$f" | sed 's/--/-/')"
done

# Prove the names on disk are the names the manifests promise, rather than
# trusting the rename above to have covered every case.
#
# grep rather than jq or python3: this also runs inside the pinned homebrew/brew
# image for the Linux legs, which carries neither.
expected="$(mktemp)"
for json in ./*.json; do
  grep -o '"filename":[[:space:]]*"[^"]*"' "$json" | sed 's/.*"\([^"]*\)"$/\1/'
done > "$expected"

# Redirected from a file, not piped: a `while read` on the far side of a pipe
# runs in a subshell and its findings would be discarded at the loop's end.
missing=""
while read -r want; do
  [ -n "$want" ] || continue
  [ -f "$want" ] || missing="$missing $want"
done < "$expected"
rm -f "$expected"
if [ -n "$missing" ]; then
  echo "::error::manifests name bottles that are not on disk:$missing" >&2
  ls -l
  exit 1
fi

echo "=== bottles built ==="
ls -l "$outdir"
