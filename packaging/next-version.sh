#!/usr/bin/env bash
# Compute the next release or prerelease version from the existing git tags.
#   next-version.sh <patch|minor|major> [--rc]
# Prints `version=`, `tag=`, and `previous=` (the stable tag the bump started from, empty for a
# first release) as key=value lines. --rc appends the next `-rc.N` counter for that base, derived
# from existing `v<base>-rc.*` tags.
#
# Release and prerelease each call this from BOTH their gate and tag jobs: the tag job re-deriving
# the same version on a tree the gate never touched — then refusing to push unless it hashes to
# what the gate qualified — is what proves the gate's intent, not textual duplication of this
# arithmetic. Both jobs calling the same script here is therefore correct, not a regression of that
# property.
set -euo pipefail
bump="${1:?usage: next-version.sh <patch|minor|major> [--rc]}"
rc=false
[ "${2:-}" != "--rc" ] || rc=true

PREV_TAG=$(git tag -l 'v*.*.*' --sort=-v:refname \
  | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1 || true)
CURRENT="${PREV_TAG#v}"; CURRENT="${CURRENT:-0.0.0}"
IFS=. read -r MAJOR MINOR PATCH <<<"$CURRENT"
case "$bump" in
  patch) PATCH=$((PATCH + 1)) ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  *) echo "invalid version bump: $bump" >&2; exit 1 ;;
esac
BASE="${MAJOR}.${MINOR}.${PATCH}"

if [ "$rc" = true ]; then
  # Numeric max of existing v<base>-rc.<n>, + 1: robust to however git version-sorts prerelease
  # suffixes.
  LAST=$(git tag -l "v${BASE}-rc.*" \
    | grep -E "^v${MAJOR}\\.${MINOR}\\.${PATCH}-rc\\.[0-9]+$" \
    | sed -E 's/.*-rc\.//' | sort -n | tail -n1 || true)
  VERSION="${BASE}-rc.$(( ${LAST:-0} + 1 ))"
else
  VERSION="$BASE"
fi
echo "version=${VERSION}"
echo "tag=v${VERSION}"
echo "previous=${PREV_TAG}"
