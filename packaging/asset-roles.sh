#!/usr/bin/env bash
# The release matrix reconcile-releases.sh replicates, and what it deliberately leaves alone.
#
# Sourced, never executed. Kept out of the shared script because this is the one genuinely
# per-project part: which artifacts a release of THIS project carries.
#
# Names taken from a real published release rather than constructed, because reconcile walks every
# surviving tag and older ones were named differently.

_ASSET_ROLES=(
  'whiskerless_*_amd64.deb'
  'whiskerless_*_arm64.deb'
  'whiskerless-*.x86_64.rpm'
  'whiskerless-*.aarch64.rpm'
  'whiskerless-*-macos-arm64.pkg'
  'whiskerless-*-macos-x86_64.pkg'
  # The standalone binaries carry no extension at all.
  'whiskerless-*-linux-x86_64'
  'whiskerless-*-linux-arm64'
  # One file, one name, every release.
  'SHA256SUMS'
)

# Homebrew bottles are NOT reconciled, and that is deliberate rather than an oversight.
#
# Reconcile's whole model is a content quorum over immutable bytes: two registries agreeing proves
# what the third should serve. A bottle is not reproducible — its gzip header carries the build
# timestamp, checked against a real published bottle — so a rebuilt bottle legitimately differs from
# its siblings, and the quorum would report a conflict for a release that is perfectly healthy.
#
# Their integrity is guaranteed by a different mechanism that suits them better: the tap's
# `bottle do` block records each bottle's sha256, bottle-block.py refuses to write a partial set,
# and the second tap pass verifies every archive the manifests name hashes to what is recorded
# before publishing the block at all.
_IGNORED_ASSETS=(
  '*.bottle.tar.gz'
  '*.bottle.json'
)
