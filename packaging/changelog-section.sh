#!/usr/bin/env bash
# Print the body of one CHANGELOG.md section, used as the release notes.
#   changelog-section.sh 1.2.3   ->  everything under "## [1.2.3]" up to the next heading
set -euo pipefail
cd "$(dirname "$0")/.."

version="${1:?usage: changelog-section.sh <version>}"

# A prerelease tag has no section of its own — the notes still live under [Unreleased] until the
# stable release promotes them — so read those instead of emitting empty release notes. Matched on
# any semver prerelease rather than `-rc.` specifically: the rule is a property of prereleases, not
# of the one suffix these projects happen to use.
case "$version" in
  *-*) version="Unreleased" ;;
esac

# The version is compared LITERALLY, as a prefix: interpolated into a regex, its dots are wildcards,
# so asking for 1.2.3 also matches a malformed `## [1x2y3]` heading and the missing-section guard
# then emits somebody else's notes instead of failing. A prefix, not equality, because Keep a
# Changelog puts the date after the bracket.
# Stops at the next heading OR the first link-reference definition, because a Keep a Changelog file
# collects its `[1.2.3]: https://…` refs at the foot — inside the last section's range, but not part
# of its notes. Absent heading fails loudly; an empty body under a real heading is fine.
awk -v ver="$version" '
  index($0, "## [" ver "]") == 1        { found = 1; grab = 1; next }
  grab && (/^## / || /^\[[^]]*\]:/)    { exit }
  grab { if (started || $0 != "") { started = 1; print } }
  END  { if (!found) { print "no CHANGELOG section for " ver > "/dev/stderr"; exit 1 } }
' CHANGELOG.md
