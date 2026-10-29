#!/usr/bin/env bash
# Install the signed .pkg, prove it is the build it claims to be, run the installed smoke, then
# remove it the way a user would and prove the store survives. The twin of dreame-valetudo's script
# of the same name; whiskerless installs one binary, so there are no helpers or libexec tree.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <package.pkg> <arm64> <version>" >&2
  exit 2
fi

pkg=$1
version=$3
bin=/usr/local/bin/whiskerless
identifier=com.sisyphusmd.whiskerless
test_home=$(mktemp -d)

cleanup() {
  sudo rm -f "$bin"
  sudo pkgutil --forget "$identifier" >/dev/null 2>&1 || true
  rm -rf "$test_home"
}
trap cleanup EXIT

mkdir -p "$test_home/whiskerless"
printf 'keep\n' > "$test_home/whiskerless/uninstall-must-preserve"

# Gatekeeper's own verdict first: `installer` does not enforce notarization, so a successful
# install proves nothing about whether a user could run it.
spctl -a -vvv -t install "$pkg" 2>&1 | tee /tmp/spctl.txt
grep -qi accepted /tmp/spctl.txt
grep -qi notarized /tmp/spctl.txt \
  || { echo "::error::pkg is signed but NOT notarized" >&2; exit 1; }
pkgutil --check-signature "$pkg"
xcrun stapler validate "$pkg"
sudo installer -pkg "$pkg" -target /

pkgutil --pkg-info "$identifier" | grep -Fx "version: $version"
test -x "$bin"
codesign --verify --strict "$bin"
bash packaging/installed-smoke.sh "$bin" "$version"

# The removal a user is told to run, answered yes, so a broken uninstall fails the release rather
# than the user. It names the receipt as a manual step, which is then done by hand as instructed.
out=$(printf 'y\n' | HOME="$test_home" "$bin" uninstall 2>&1) \
  || { printf '%s\n' "$out" >&2; echo "::error::whiskerless uninstall failed" >&2; exit 1; }
printf '%s\n' "$out"
grep -Fq "macOS .pkg" <<<"$out" \
  || { echo "::error::uninstall did not find the .pkg it was run from" >&2; exit 1; }
grep -Fq "pkgutil --forget $identifier" <<<"$out" \
  || { echo "::error::uninstall did not name the receipt to forget" >&2; exit 1; }
sudo pkgutil --forget "$identifier"

{ [ ! -e "$bin" ] && [ ! -L "$bin" ]; } || { echo "::error::uninstall left $bin behind" >&2; exit 1; }
if pkgutil --pkgs | grep -qx "$identifier"; then
  echo "::error::the package receipt survived" >&2
  exit 1
fi
test -f "$test_home/whiskerless/uninstall-must-preserve" \
  || { echo "::error::uninstall removed the user's store" >&2; exit 1; }
echo "macOS package test PASS: $pkg"
