#!/usr/bin/env bash
# Run pinned shellcheck at DEFAULT severity over every shipped and integration script, via a
# throwaway container so no host shellcheck install is required.
#
# One script rather than an inline block, called by ci.yml's shellcheck job AND by the
# release/prerelease gates: pre-merge and pre-tag then enforce the same check by construction
# rather than by three copies of it staying in agreement.
set -euo pipefail
# The tree to scan, defaulting to this script's parent directory — the repo root in a consumer, which
# vendors it to packaging/. A project that keeps it deeper has to say so: `git ls-files` is relative
# to the working directory, so the default would silently scan a SUBTREE and report a clean pass
# while every script outside it went unchecked.
cd "${1:-$(dirname "$0")/..}"
# renovate: datasource=docker depName=koalaman/shellcheck
SHELLCHECK="koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d"
# Every tracked *.sh, not three globbed directories: a script added anywhere else used to go
# unchecked because nobody widened the list.
mapfile -t scripts < <(git ls-files '*.sh')
cid=$(docker create -w /work "$SHELLCHECK" "${scripts[@]}")
docker cp . "$cid":/work
check_rc=0
docker start -a "$cid" || check_rc=$?
docker rm "$cid" >/dev/null
exit "$check_rc"
