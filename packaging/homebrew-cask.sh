#!/usr/bin/env bash
# Regenerate the Homebrew cask for a published release.
#
#     packaging/homebrew-cask.sh 0.2.0 [> path/to/tap/Casks/whiskerless.rb]
#
# Reads the two .pkg assets straight off the GitHub release and hashes them, so
# the checksums describe what users will actually download rather than what a
# local build happened to produce.
set -euo pipefail

version="${1:?usage: homebrew-cask.sh <version>}"
version="${version#v}"
base="https://github.com/SisyphusMD/whiskerless/releases/download/v${version}"

sha_for() {
  local arch="$1" tmp
  tmp="$(mktemp)"
  if ! curl -sSfL -o "$tmp" "${base}/whiskerless-macos-${arch}.pkg"; then
    echo "error: no ${arch} .pkg on release v${version}" >&2
    exit 1
  fi
  shasum -a 256 "$tmp" | cut -d' ' -f1
  rm -f "$tmp"
}

arm_sha="$(sha_for arm64)"
intel_sha="$(sha_for x86_64)"

# Everything but the version and the two hashes is copied from the checked-in
# source of truth, so edits there survive a regeneration.
sed \
  -e "s/^  version \".*\"$/  version \"${version}\"/" \
  -e "s/^  sha256 arm:   \".*\",$/  sha256 arm:   \"${arm_sha}\",/" \
  -e "s/^         intel: \".*\"$/         intel: \"${intel_sha}\"/" \
  "$(dirname "$0")/homebrew/whiskerless.rb"
