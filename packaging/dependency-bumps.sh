#!/usr/bin/env bash
# Print Renovate dependency-bump commit subjects since <prev-tag>, newest first, deduped to the
# latest bump per dependency (git log is newest-first, so the first key seen is the latest; the
# dedup key is the DEPENDENCY NAME alone, cut from between "update " and " to " and then stripped of
# Renovate's "dependency " prefix and its type qualifier. Trimming only a trailing " to <version>"
# leaves the version in the key whenever a subject carries a trailing note, and keeping the qualifier
# makes "<dep> action" a different dependency from "<dep>" when one bump was written by hand).
# `: update ` is required, not just the `(deps)` scope: hand-written policy commits use that scope too
# ("fix(deps): hold setup-python bumps until ..."), and they carry no " to <version>" for the dedup to
# strip, so each one reaches the release notes whole as a bullet that describes no dependency change.
#   dependency-bumps.sh [prev-tag]
# A first release (no previous tag) has nothing to compare against: the deps it ships ARE the
# initial set, not updates from a prior release, so it prints nothing even if Renovate bumps landed
# before the first tag.
set -euo pipefail
cd "$(dirname "$0")/.."
prev="${1:-}"
[ -n "$prev" ] || exit 0
# Captured on its own line so a `prev` that does not resolve is fatal. Folded into the pipeline, the
# trailing `|| true` below would swallow that too, and the release would publish a changelog with an
# empty Dependencies section rather than stop. The `|| true` exists only for grep finding no bumps.
subjects="$(git log "${prev}..HEAD" --pretty=format:'%s')"
printf '%s\n' "$subjects" \
  | grep -E '^(chore|fix)\(deps\): update ' \
  | awk '{ key=$0
           sub(/^.*: update /, "", key); sub(/ to .*$/, "", key)
           sub(/^dependency /, "", key)
           sub(/ (docker digest|docker tag|docker image|action|digest|tag|image)$/, "", key)
           if (!seen[key]++) print }' || true
