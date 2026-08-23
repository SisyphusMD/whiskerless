#!/usr/bin/env bash
# Promote "## [Unreleased]" in CHANGELOG.md into a dated release heading, appending the optional
# "### Dependencies" block from $DEPS (one Renovate commit subject per line).
#   DEPS=... promote-changelog.sh 1.2.3 2026-01-31
# The release workflow runs this on two separate runners and byte-compares the results, so the date
# is an argument rather than "now": the two runs must not disagree across a UTC midnight.
set -euo pipefail
cd "$(dirname "$0")/.."
ver="${1:?version required}"
date="${2:?release date (YYYY-MM-DD) required}"
[[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "invalid release date: $date" >&2; exit 1; }
# Counted, not merely found: the awk below rewrites EVERY match, so a merge that left two Unreleased
# headings would promote both and produce duplicate release sections. The final guard checks that the
# new heading exists, which it would, so nothing downstream notices.
unreleased="$(grep -cE '^## \[Unreleased\]' CHANGELOG.md || true)"
[ "$unreleased" = 1 ] || {
  echo "expected exactly one '## [Unreleased]' heading, found $unreleased" >&2; exit 1; }

DEPS="${DEPS:-}"
export DEPS
trap 'rm -f CHANGELOG.md.new' EXIT
# ENVIRON["DEPS"] (not -v) so awk doesn't backslash-process the subjects. Appends a "### Dependencies"
# block to the just-promoted version's section: before the next existing ## [ ] section, or at
# end-of-file for the first release.
awk -v ver="$ver" -v date="$date" '
  BEGIN { in_section=0; emitted=0; deps=ENVIRON["DEPS"] }
  /^## \[Unreleased\]/ {
    print "## [Unreleased]"; print ""; print "## [" ver "] - " date
    in_section=1; next
  }
  in_section && /^## \[/ {
    if (!emitted && deps != "") {
      print "### Dependencies"; print ""
      n=split(deps, lines, "\n")
      for (i=1;i<=n;i++) if (lines[i] != "") print "- " lines[i]
      print ""; emitted=1
    }
    in_section=0; print; next
  }
  { print }
  END {
    if (in_section && !emitted && deps != "") {
      print ""; print "### Dependencies"; print ""
      n=split(deps, lines, "\n")
      for (i=1;i<=n;i++) if (lines[i] != "") print "- " lines[i]
    }
  }
' CHANGELOG.md > CHANGELOG.md.new
mv CHANGELOG.md.new CHANGELOG.md
# Fail closed: never hand a workflow a CHANGELOG that silently kept its Unreleased-only shape.
grep -qxF "## [${ver}] - ${date}" CHANGELOG.md || { echo "promotion did not apply" >&2; exit 1; }
