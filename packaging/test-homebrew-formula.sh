#!/usr/bin/env bash
# Install the rendered Homebrew formula from a LOCAL sdist and run it — the check that was
# missing when bleak 3.x's uv_build backend made every `brew install` fail AFTER the tap had
# already published (backlog #29). What is proved is the template + its resource closure
# building under Homebrew's --no-binary rules, not PyPI's availability.
#
# Installs and uninstalls a real formula, so it runs only on disposable workers (the
# homebrew-smoke container, a fresh CI runner) — never point it at a developer's brew.
#   test-homebrew-formula.sh <vX.Y.Z[-rc.N]> <sdist.tar.gz>
set -euo pipefail
export HOMEBREW_NO_AUTOREMOVE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 HOMEBREW_NO_AUTO_UPDATE=1

[ "$#" -eq 2 ] || { echo "usage: $0 <vX.Y.Z[-rc.N]> <sdist.tar.gz>" >&2; exit 2; }
tag="$1"
sdist="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
version="${tag#v}"
# PEP 440: the tag says 0.2.0-rc.1, PyPI (and the sdist filename) say 0.2.0rc1.
pypi_version="$(printf '%s' "$version" | sed -E 's/-rc\.([0-9]+)$/rc\1/')"
here="$(cd "$(dirname "$0")" && pwd)"

case "$version" in
  *-*) formula=whiskerless-rc ;;
  *)   formula=whiskerless ;;
esac
if brew list --formula "$formula" >/dev/null 2>&1; then
  echo "this machine already has $formula installed — refusing to touch a real brew" >&2
  exit 1
fi
[ -f "$sdist" ] || { echo "no sdist at $sdist" >&2; exit 2; }

if command -v sha256sum >/dev/null 2>&1; then shacmd="sha256sum"; else shacmd="shasum -a 256"; fi
sha="$($shacmd "$sdist" | awk '{print $1}')"

tmp="$(mktemp -d)"
tap=sisyphusmd/formula-smoke
tap_created=false
cleanup() {
  if [ "$tap_created" = true ]; then
    brew uninstall --force "$tap/$formula" >/dev/null 2>&1 || true
    brew untap "$tap" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

# Rendered exactly as update-tap.sh renders it, except the url points at the local sdist.
sed -e "s|REPLACE_PYPI_VERSION|${pypi_version}|g" \
    -e "s|REPLACE_VERSION|${pypi_version}|g" \
    -e "s|REPLACE_SDIST_SHA256|${sha}|" \
    "$here/homebrew/${formula}.rb" \
  | sed -e "s|^  url \".*\"$|  url \"file://${sdist}\"|" \
  > "$tmp/$formula.rb"
if ! grep -Fq "file://$sdist" "$tmp/$formula.rb" \
  || grep -Eq 'REPLACE_(PYPI_)?VERSION|REPLACE_SDIST_SHA256' "$tmp/$formula.rb"; then
  echo "formula rendering failed" >&2
  exit 1
fi

brew tap-new --no-git "$tap" >/dev/null
tap_created=true
cp "$tmp/$formula.rb" "$(brew --repository "$tap")/Formula/$formula.rb"
brew install "$tap/$formula"
brew test "$tap/$formula"

cli="$(brew --prefix)/bin/whiskerless"
# __version__ carries the tag spelling (0.2.0-rc.1) while the sdist carries PEP 440; accept either.
out="$("$cli" --version)"
case "$out" in
  *"$version"*|*"$pypi_version"*) : ;;
  *) echo "installed CLI reports the wrong version: $out (wanted $version)" >&2; exit 1 ;;
esac
"$cli" send --help >/dev/null

echo "Homebrew formula smoke PASS: $formula $pypi_version"
