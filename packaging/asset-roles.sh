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
  # Intel Macs are no longer built for, but stable releases that shipped an Intel .pkg are never
  # pruned, and this role is what lets reconcile repair a missing copy of one. Newer tags log a
  # warn-only "no asset matches" for it.
  'whiskerless-*-macos-x86_64.pkg'
  # The standalone binaries carry no extension at all.
  'whiskerless-*-linux-x86_64'
  'whiskerless-*-linux-arm64'
  # One checksum file per architecture, each written by the machine that built those bytes. Named
  # for `uname -m` so the verify command is copy-pasteable. Listed separately rather than as a
  # `SHA256SUMS-*` glob: one role matching two names is what resolve_expected calls ambiguous, and
  # it skips the whole tag for it.
  #
  # The pre-split `SHA256SUMS` is deliberately NOT kept alongside them. Reconcile walks every
  # surviving tag, so the question is which surviving tags carry that name: checked against the
  # live releases, it is eight v0.2.0-rc.* and no stable, and every one of those is deleted by
  # prune-rcs the moment 0.2.0 ships. A third role would earn a permanent "no asset matches" on
  # every release thereafter to heal releases that are about to stop existing.
  'SHA256SUMS-x86_64'
  'SHA256SUMS-aarch64'
)

# Roles reconcile should heal but completeness must NOT demand of a release that predates them. Both
# install matrices deliberately support dispatching the CURRENT scripts against an OLDER tag - that
# is what the tag input is for - and wait-for-release.sh would otherwise wait out its whole deadline
# and then fail a release that is perfectly complete. Reconcile keeps them above, where a missing
# role is a warning rather than a verdict. The wait still treats them as all-or-nothing: a release
# carrying either checksum was cut after they existed, so the other is late, not absent.
_OPTIONAL_ASSET_ROLES=(
  'SHA256SUMS-x86_64'
  'SHA256SUMS-aarch64'
)

# What a release cut before the optional roles carries in their place, which the wait then demands
# instead: the single pre-split `SHA256SUMS` the surviving v0.2.0-rc.* releases carry. Not a role
# (see above), so reconcile never asks for it; only the wait accepts it, and only in lieu of the pair.
_OPTIONAL_ASSET_PREDECESSORS=(
  'SHA256SUMS'
)

# Homebrew bottles are NOT reconciled, and that is deliberate rather than an oversight. Note the
# narrow claim: not reconciled, which is not the same as not mirrored. The NAS carries a complete
# copy via the nas-bottles job — copying is not comparing, and the objection below is only to
# comparing.
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
